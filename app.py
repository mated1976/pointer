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
import glob

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

# Image compression quality (80%)
COMPRESSION_QUALITY = 80

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

# Dynamic overlay image loading function
def load_overlay_images():
    """Dynamically load all overlay images from the overlay folder"""
    overlay_path = os.path.join(app.config['OVERLAY_FOLDER'], '*.webp')
    image_files = glob.glob(overlay_path)
    
    # Sort files by name to ensure consistent ordering
    image_files.sort()
    
    # Extract just the filenames
    return [os.path.basename(f) for f in image_files]

# Initialize the overlay images when the app starts
HAND_IMAGES = []

# Load the images during initialization
def initialize_overlay_images():
    global HAND_IMAGES
    HAND_IMAGES = load_overlay_images()
    if not HAND_IMAGES:
        print("WARNING: No overlay images found in", app.config['OVERLAY_FOLDER'])

# Call this function after directories are created
initialize_overlay_images()

# Lighting adjustment parameters
# Baseline represents the "normal" lighting conditions the overlays were photographed in
# Higher values make overlays less responsive to background lighting
LIGHTING_BASELINE = 0.97  # Value between 0.0 and 1.0
LIGHTING_SENSITIVITY = 1.0  # How strongly to adjust (1.0 = normal, higher = more dramatic)

def adjust_overlay_to_match_lighting(base_image, overlay_image, click_x, click_y):
    """Adjust overlay brightness to match the base image lighting in the area of placement"""
    # Sample area where overlay will be placed
    sample_size = 500  # pixels around click point
    x1 = max(0, click_x - sample_size//2)
    y1 = max(0, click_y - sample_size//2)
    x2 = min(base_image.width, click_x + sample_size//2)
    y2 = min(base_image.height, click_y + sample_size//2)
    
    # Calculate average brightness in sample area
    sample = base_image.crop((x1, y1, x2, y2))
    sample_array = np.array(sample.convert('L'))
    avg_brightness = np.mean(sample_array) / 255.0  # 0.0 to 1.0
    
    # Create brightness adjusted overlay
    overlay_array = np.array(overlay_image)
    
    # Skip transparent pixels (alpha == 0)
    mask = overlay_array[:,:,3] > 0
    
    # Calculate brightness factor from baseline
    brightness_factor = LIGHTING_BASELINE + ((avg_brightness - 0.5) * LIGHTING_SENSITIVITY)
    brightness_factor = max(0.3, min(1.7, brightness_factor))  # Clamp to reasonable range
    
    # Apply brightness adjustment to RGB channels
    overlay_array[mask, 0:3] = np.clip(overlay_array[mask, 0:3] * brightness_factor, 0, 255).astype(np.uint8)
    
    # Return adjusted overlay
    return Image.fromarray(overlay_array)

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
            'hand_index': data.get('handIndex', 0),
            'flip': data.get('flip', False)
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
            rgb_image.save(compressed_image, format='JPEG', quality=COMPRESSION_QUALITY)
        else:
            base_image.save(compressed_image, format='JPEG', quality=COMPRESSION_QUALITY)
        
        compressed_image.seek(0)
        base_image = Image.open(compressed_image).convert('RGBA')
        
        # Get click position
        click_x = int(data['x'])
        click_y = int(data['y'])
        
        # Determine if we should flip the image (if click is on right side)
        should_flip = click_x > base_image.width / 2
        
        # Get the hand overlay index or start with 0
        hand_index = int(data.get('handIndex', 0)) % len(HAND_IMAGES)
        overlay_file = HAND_IMAGES[hand_index]
        
        # Get overlay image
        overlay_path = os.path.join(app.config['OVERLAY_FOLDER'], overlay_file)
        if not os.path.exists(overlay_path):
            return jsonify({'error': f'Overlay image not found: {overlay_file}'}), 404
            
        overlay_image = Image.open(overlay_path).convert('RGBA')
        
        # Flip the image if needed
        if should_flip:
            overlay_image = overlay_image.transpose(Image.FLIP_LEFT_RIGHT)
        
        # Calculate position to place overlay based on which side was clicked
        if should_flip:  # Right side click
            # Use direct placement at click position
            x_offset = click_x
            y_offset = click_y
        else:  # Left side click
            # Use top right corner of overlay for alignment
            x_offset = click_x - overlay_image.width
            y_offset = click_y
        
        # Create a new transparent image of the same size as base image
        result = Image.new('RGBA', base_image.size, (0, 0, 0, 0))
        
        # Paste base image
        result.paste(base_image, (0, 0))
        
        # Adjust overlay lighting to match background
        adjusted_overlay = adjust_overlay_to_match_lighting(base_image, overlay_image, click_x, click_y)
        
        # Paste adjusted overlay image at calculated position
        result.paste(adjusted_overlay, (x_offset, y_offset), adjusted_overlay)
        
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
            'nextHandIndex': (hand_index + 1) % len(HAND_IMAGES)
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