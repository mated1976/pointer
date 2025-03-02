document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const imageUpload = document.getElementById('imageUpload');
    const cameraUpload = document.getElementById('cameraUpload');
    const previewImage = document.getElementById('previewImage');
    const overlayCanvas = document.getElementById('overlayCanvas');
    const imageContainer = document.getElementById('imageContainer');
    const resultContainer = document.getElementById('resultContainer');
    const resultImage = document.getElementById('resultImage');
    const controlsContainer = document.querySelector('.controls');
    const actionButtons = document.getElementById('actionButtons');
    const instruction = document.getElementById('instruction');
    const tryDifferentBtn = document.getElementById('tryDifferent');
    const saveImageBtn = document.getElementById('saveImage');
    const newImageBtn = document.getElementById('newImage');
    
    // Variables
    let currentImage = null;
    let lastClickX = 0;
    let lastClickY = 0;
    let currentOverlayIndex = 0;
    let firstClickDone = false;
    
    // Event listeners
    imageUpload.addEventListener('change', handleImageUpload);
    if (cameraUpload) {
        cameraUpload.addEventListener('change', handleImageUpload);
    }
    previewImage.addEventListener('click', handleImageClick);
    tryDifferentBtn.addEventListener('click', tryDifferentOverlay);
    saveImageBtn.addEventListener('click', saveImage);
    newImageBtn.addEventListener('click', resetApp);
    
    // Handle image upload or capture
    function handleImageUpload(e) {
        const file = e.target.files[0];
        if (!file) return;
        
        const reader = new FileReader();
        reader.onload = (event) => {
            currentImage = event.target.result;
            
            // Resize image if too large
            const img = new Image();
            img.onload = function() {
                const maxWidth = 1080;
                let width = img.width;
                let height = img.height;
                
                // Resize if width is greater than maxWidth
                if (width > maxWidth) {
                    const ratio = maxWidth / width;
                    width = maxWidth;
                    height = height * ratio;
                    
                    // Create canvas to resize
                    const canvas = document.createElement('canvas');
                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0, width, height);
                    
                    // Get resized image data - format is now kept as is,
                    // server will handle conversion to WebP
                    currentImage = canvas.toDataURL('image/jpeg', 0.9);
                }
                
                // Set the preview image
                previewImage.src = currentImage;
                
                // Show image container and hide result
                imageContainer.classList.remove('hidden');
                resultContainer.classList.add('hidden');
                
                // Hide upload controls
                controlsContainer.classList.add('hidden');
                
                // Show action buttons at top
                actionButtons.classList.remove('hidden');
                document.querySelector('.container').insertBefore(actionButtons, imageContainer);
                
                instruction.classList.remove('hidden');
                
                // Reset first click flag
                firstClickDone = false;
                
                // Reset overlay index
                currentOverlayIndex = 0;
            };
            img.src = event.target.result;
        };
        reader.readAsDataURL(file);
    }
    
    // Handle click on the image
    function handleImageClick(e) {
        // Get click coordinates relative to the image
        const rect = previewImage.getBoundingClientRect();
        const scale = previewImage.naturalWidth / rect.width;
        
        lastClickX = Math.round((e.clientX - rect.left) * scale);
        lastClickY = Math.round((e.clientY - rect.top) * scale);
        
        // Process the image with overlay
        processImage(lastClickX, lastClickY, currentOverlayIndex);
    }
    
    // Try a different overlay for the same click position
    function tryDifferentOverlay() {
        // Increment overlay index and reprocess
        currentOverlayIndex++;
        processImage(lastClickX, lastClickY, currentOverlayIndex);
    }
    
    // Process the image on the server
    function processImage(x, y, overlayIndex) {
        // Show loading state
        previewImage.style.opacity = '0.5';
        instruction.textContent = 'Processing...';
        
        // Use relative URL instead of hardcoded one
        fetch('/process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                image: currentImage,  // Always use original image
                x: x,
                y: y,
                overlayIndex: overlayIndex,
            }),
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                throw new Error(data.error);
            }
            
            // Display the result
            previewImage.src = data.result + '?t=' + new Date().getTime(); // Cache busting
            
            // Update overlay index for next try
            currentOverlayIndex = data.nextOverlayIndex;
            
            // Reset opacity and instruction
            previewImage.style.opacity = '1';
            instruction.textContent = 'Tap anywhere on the image to add a pointing hand';
        })
        .catch(error => {
            console.error('Error processing image:', error);
            instruction.textContent = 'Error processing image. Please try again.';
            instruction.style.color = 'red';
            previewImage.style.opacity = '1';
            
            // Reset after 3 seconds
            setTimeout(() => {
                instruction.textContent = 'Tap anywhere on the image to add a pointing hand';
                instruction.style.color = '';
            }, 3000);
        });
    }
    
    // Save the processed image
    function saveImage() {
        // Log save event
        fetch('/log-event', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                event: 'save_image',
                details: { 
                    screen_width: window.innerWidth,
                    screen_height: window.innerHeight
                }
            }),
        }).catch(console.error);
        
        // Create an anchor element and trigger download
        const link = document.createElement('a');
        link.href = previewImage.src;
        link.download = 'pointing-hand-' + new Date().getTime() + '.webp';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        
        // Check if on mobile and offer share option
        if (navigator.share) {
            fetch(previewImage.src)
                .then(res => res.blob())
                .then(blob => {
                    const file = new File([blob], 'pointing-hand.webp', { type: 'image/webp' });
                    navigator.share({
                        title: 'My Pointing Hand Image',
                        files: [file]
                    })
                    .then(() => {
                        // Log share event
                        fetch('/log-event', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                event: 'share_image',
                                details: { method: 'web_share_api' }
                            }),
                        }).catch(console.error);
                    })
                    .catch(console.error);
                });
        }
    }
    
    // Reset the app for a new image
    function resetApp() {
        // Hide image and action buttons
        imageContainer.classList.add('hidden');
        actionButtons.classList.add('hidden');
        
        // Show controls for uploading a new image
        controlsContainer.classList.remove('hidden');
        
        // Reset input fields
        imageUpload.value = '';
        if (cameraUpload) {
            cameraUpload.value = '';
        }
        
        // Reset state variables
        currentOverlayIndex = 0;
        firstClickDone = false;
    }
});