from flask import Flask, render_template, request, jsonify, url_for, Response
import os
import base64
from PIL import Image
import io
import numpy as np
import time
import functools
from dotenv import load_dotenv
from mysql_data_collector import MySQLDataCollector

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['OVERLAY_FOLDER'] = 'static/overlay_images'
app.config['RESULT_FOLDER'] = 'static/results'
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24))

# MySQL Database Configuration from environment variables
db_config = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'database': os.environ.get('DB_NAME', 'pointing_app'),
    'user': os.environ.get('DB_USER', ''),
    'password': os.environ.get('DB_PASSWORD', ''),
    'port': int(os.environ.get('DB_PORT', 3306))
}

# Stats access credentials
STATS_USERNAME = os.environ.get('STATS_USERNAME', 'admin')
STATS_PASSWORD = os.environ.get('STATS_PASSWORD', '')

# Image compression quality (75%)
COMPRESSION_QUALITY = 75

# Validate configuration
if not all([db_config['user'], db_config['password']]):
    print("WARNING: Database credentials not set in environment variables.")
    print("Set DB_USER and DB_PASSWORD environment variables or create a .env file.")

if not STATS_PASSWORD:
    print("WARNING: Stats password not set. Set STATS_PASSWORD in environment variables.")

# Initialize data collector with MySQL
data_collector = MySQLDataCollector(db_config)

# Ensure directories exist
for folder in [app.config['UPLOAD_FOLDER'], app.config['RESULT_FOLDER']]:
    os.makedirs(folder, exist_ok=True)

# Define left and right hand images - updated to include 5 of each
LEFT_HANDS = ['l-01.webp', 'l-02.webp', 'l-03.webp', 'l-04.webp', 'l-05.webp']
RIGHT_HANDS = ['r-01.webp', 'r-02.webp', 'r-03.webp', 'r-04.webp', 'r-05.webp']

def detect_red_dot(image_path):
    """Detect the center of the red dot in overlay images and remove it completely"""
    img = Image.open(image_path).convert('RGBA')
    img_array = np.array(img)
    
    # Look for bright red pixels (the dot is 7px)
    red_pixels = np.where(
        (img_array[:, :, 0] > 240) &  # High red
        (img_array[:, :, 1] < 30) &   # Low green
        (img_array[:, :, 2] < 30)     # Low blue
    )
    
    # Create a copy without the red dot
    img_no_dot = img.copy()
    
    if len(red_pixels[0]) > 0:
        # Find center of the red dot
        y_center = int(np.mean(red_pixels[0]))
        x_center = int(np.mean(red_pixels[1]))
        
        # Remove the red dot and expand removal by 1px to ensure full removal
        for y in range(max(0, min(red_pixels[0]) - 1), min(img.height, max(red_pixels[0]) + 2)):
            for x in range(max(0, min(red_pixels[1]) - 1), min(img.width, max(red_pixels[1]) + 2)):
                # Check if this pixel or a neighboring pixel is red
                if ((abs(y - y_center) <= 5) and (abs(x - x_center) <= 5)):
                    img_no_dot.putpixel((x, y), (0, 0, 0, 0))  # Make the red dot transparent
        
        return (x_center, y_center), img_no_dot
    
    # If no red dot found, assume center of image
    return (img.width // 2, img.height // 2), img_no_dot

# Authentication decorator for protected routes
def requires_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not (auth.username == STATS_USERNAME and auth.password == STATS_PASSWORD):
            return Response(
                'Authentication required to access statistics',
                401,
                {'WWW-Authenticate': 'Basic realm="Stats Access"'}
            )
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    # Log page visit
    data_collector.log_usage('page_visit')
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_image():
    data = request.json
    
    try:
        # Validate required inputs
        if 'image' not in data or 'x' not in data or 'y' not in data:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Log image processing
        data_collector.log_usage('process_image', {
            'click_x': data.get('x'),
            'click_y': data.get('y'),
            'overlay_index': data.get('overlayIndex', 0)
        })
        
        # Get the base image from the data URL
        image_parts = data['image'].split(',')
        if len(image_parts) < 2:
            return jsonify({'error': 'Invalid image data'}), 400
            
        image_data = image_parts[1]
        image_bytes = base64.b64decode(image_data)
        base_image = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
        
        # Compress the base image
        compressed_image = io.BytesIO()
        if base_image.mode == 'RGBA':
            # Convert to RGB for better WebP compression
            rgb_image = Image.new('RGB', base_image.size, (255, 255, 255))
            rgb_image.paste(base_image, mask=base_image.split()[3])  # Use alpha as mask
            rgb_image.save(compressed_image, format='WEBP', quality=COMPRESSION_QUALITY)
        else:
            base_image.save(compressed_image, format='WEBP', quality=COMPRESSION_QUALITY)
        
        compressed_image.seek(0)
        base_image = Image.open(compressed_image).convert('RGBA')
        
        # Get click position
        click_x = int(data['x'])
        click_y = int(data['y'])
        
        # Determine which hand to use based on click position
        is_left_side = click_x < base_image.width / 2
        overlay_files = LEFT_HANDS if is_left_side else RIGHT_HANDS
        
        # Get the current overlay index or start with 0
        overlay_index = int(data.get('overlayIndex', 0)) % len(overlay_files)
        overlay_file = overlay_files[overlay_index]
        
        # Get overlay image and find the red dot position
        overlay_path = os.path.join(app.config['OVERLAY_FOLDER'], overlay_file)
        if not os.path.exists(overlay_path):
            return jsonify({'error': f'Overlay image not found: {overlay_file}'}), 404
            
        (dot_x, dot_y), overlay_image = detect_red_dot(overlay_path)
        
        # Calculate position to place overlay (centering the dot on click position)
        x_offset = click_x - dot_x
        y_offset = click_y - dot_y
        
        # Create a new transparent image of the same size as base image
        result = Image.new('RGBA', base_image.size, (0, 0, 0, 0))
        
        # Paste base image
        result.paste(base_image, (0, 0))
        
        # Paste overlay image at calculated position
        result.paste(overlay_image, (x_offset, y_offset), overlay_image)
        
        # Save result as JPG
        timestamp = int(time.time())
        result_filename = f"result_{timestamp}.jpg"
        result_path = os.path.join(app.config['RESULT_FOLDER'], result_filename)
        
        # Convert to RGB for JPG (which doesn't support alpha)
        if result.mode == 'RGBA':
            rgb_result = Image.new('RGB', result.size, (255, 255, 255))
            rgb_result.paste(result, mask=result.split()[3])
            rgb_result.save(result_path, format='JPEG', quality=COMPRESSION_QUALITY)
        else:
            result.save(result_path, format='JPEG', quality=COMPRESSION_QUALITY)
        
        # Return paths to the frontend
        return jsonify({
            'result': url_for('static', filename=f'results/{result_filename}'),
            'nextOverlayIndex': (overlay_index + 1) % len(overlay_files)
        })
    except Exception as e:
        # Log the error
        data_collector.log_usage('process_error', {'error': str(e)})
        return jsonify({'error': 'An error occurred processing the image'}), 500

@app.route('/log-event', methods=['POST'])
def log_event():
    """Endpoint for client-side logging"""
    data = request.json
    
    try:
        # Validate input
        if 'event' not in data:
            return jsonify({'error': 'Missing event parameter'}), 400
            
        event_type = data.get('event')
        details = data.get('details', {})
        
        # Log the event
        data_collector.log_usage(event_type, details)
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/stats', methods=['GET'])
@requires_auth
def get_stats():
    """Get usage statistics (protected with authentication)"""
    try:
        days = request.args.get('days', default=7, type=int)
        if days < 1 or days > 365:  # Reasonable limits
            days = 7
            
        stats = data_collector.get_stats(days)
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def page_not_found(e):
    return jsonify({'error': 'Page not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)