// Global variables
let currentImage = null;
let handIndex = 0;
let resultUrl = null;

// DOM Elements
const imageUpload = document.getElementById('imageUpload');
const cameraUpload = document.getElementById('cameraUpload');
const previewImage = document.getElementById('previewImage');
const imageContainer = document.getElementById('imageContainer');
const resultContainer = document.getElementById('resultContainer');
const actionButtons = document.getElementById('actionButtons');
const resultImage = document.getElementById('resultImage');
const instruction = document.getElementById('instruction');
const tryDifferentBtn = document.getElementById('tryDifferent');
const saveImageBtn = document.getElementById('saveImage');
const newImageBtn = document.getElementById('newImage');
const overlayCanvas = document.getElementById('overlayCanvas');

// Setup event listeners
imageUpload.addEventListener('change', handleImageSelect);
cameraUpload.addEventListener('change', handleImageSelect);
previewImage.addEventListener('click', handleImageClick);
tryDifferentBtn.addEventListener('click', tryDifferentHand);
saveImageBtn.addEventListener('click', saveResultImage);
newImageBtn.addEventListener('click', resetApp);

// Log usage event to server
function logEvent(event, details = {}) {
    fetch('/log-event', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            event: event,
            details: details
        })
    }).catch(error => console.error('Error logging event:', error));
}

// Handle image selection from gallery or camera
function handleImageSelect(e) {
    const file = e.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(event) {
            currentImage = event.target.result;
            previewImage.src = currentImage;
            showImageContainer();
            // Log image selection
            logEvent('image_selected', {
                source: e.target.id === 'imageUpload' ? 'gallery' : 'camera',
                imageType: file.type
            });
        };
        reader.readAsDataURL(file);
    }
}

// Show the image container and hide result
function showImageContainer() {
    imageContainer.classList.remove('hidden');
    resultContainer.classList.add('hidden');
    instruction.classList.remove('hidden');
    actionButtons.classList.add('hidden');
}

// Handle click on the image
function handleImageClick(e) {
    if (!currentImage) return;
    
    // Calculate click position relative to the image
    const rect = previewImage.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Log the click position for debugging
    console.log(`Click at x: ${x}, y: ${y}, handIndex: ${handIndex}`);
    
    // Process the image with current hand index
    processImage(x, y, handIndex);
    
    // Log the click event
    logEvent('image_clicked', {
        x: Math.round(x),
        y: Math.round(y),
        imageWidth: previewImage.width,
        imageHeight: previewImage.height,
        handIndex: handIndex
    });
}

// Send image to server for processing
function processImage(x, y, currentHandIndex) {
    // Show loading state
    document.body.classList.add('loading');
    
    // Logging for debugging
    console.log(`Processing image with handIndex: ${currentHandIndex}`);
    
    fetch('/process', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            image: currentImage,
            x: x,
            y: y,
            handIndex: currentHandIndex
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }
        
        // Update the hand index for next time
        handIndex = data.nextHandIndex;
        console.log(`New handIndex received: ${handIndex}`);
        
        // Show the result
        resultUrl = data.result;
        resultImage.src = resultUrl + '?t=' + new Date().getTime(); // Force reload
        
        // Show result container and buttons
        resultContainer.classList.remove('hidden');
        imageContainer.classList.add('hidden');
        actionButtons.classList.remove('hidden');
        
        // Log success
        logEvent('image_processed', {
            success: true,
            handIndex: currentHandIndex,
            nextHandIndex: handIndex
        });
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error processing image. Please try again.');
        
        // Log error
        logEvent('process_error', {
            error: error.toString()
        });
    })
    .finally(() => {
        // Hide loading state
        document.body.classList.remove('loading');
    });
}

// Try a different hand overlay
function tryDifferentHand() {
    // Make sure we have the current image
    if (!currentImage) return;
    
    // Reset to image selection view
    showImageContainer();
    
    // Increment hand index (handled by the server response now)
    console.log(`Using handIndex: ${handIndex} for try different`);
    
    // Log the event
    logEvent('try_different_hand', {
        currentHandIndex: handIndex
    });
}

// Save the result image
function saveResultImage() {
    if (!resultUrl) return;
    
    // Create a temporary link to download the image
    const link = document.createElement('a');
    link.href = resultUrl;
    link.download = 'pointing_' + new Date().getTime() + '.jpg';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    // Log save event
    logEvent('image_saved');
}

// Reset the app to initial state
function resetApp() {
    currentImage = null;
    handIndex = 0; // Reset hand index
    resultUrl = null;
    
    // Reset file inputs
    imageUpload.value = '';
    cameraUpload.value = '';
    
    // Hide containers
    imageContainer.classList.add('hidden');
    resultContainer.classList.add('hidden');
    actionButtons.classList.add('hidden');
    
    // Log reset event
    logEvent('app_reset');
}
