function updateSpeed() {
    const slider = document.getElementById('speedSlider');
    const valueDisplay = document.getElementById('speedValue');
    valueDisplay.textContent = slider.value;
}

function showMessage(elementId, message, isError = false) {
    const msgElement = document.getElementById(elementId);
    msgElement.textContent = message;
    msgElement.className = 'message ' + (isError ? 'error' : 'success');
    msgElement.style.display = 'block';
    setTimeout(() => {
        msgElement.style.display = 'none';
    }, 3000);
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];

    if (!file) {
        showMessage('uploadMessage', 'Please select a file', true);
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            showMessage('uploadMessage', 'File uploaded and parsed successfully!');
        } else {
            showMessage('uploadMessage', data.error || 'Upload failed', true);
        }
    } catch (error) {
        showMessage('uploadMessage', 'Error: ' + error.message, true);
    }
}

async function sendControl(direction) {
    const speed = parseInt(document.getElementById('speedSlider').value);

    try {
        const response = await fetch('/control', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                direction: direction,
                speed: speed
            })
        });

        const data = await response.json();

        if (response.ok) {
            showMessage('controlMessage', `${data.action} with speed ${data.speed}`);
        } else {
            showMessage('controlMessage', data.error || 'Control failed', true);
        }
    } catch (error) {
        showMessage('controlMessage', 'Error: ' + error.message, true);
    }
}

// Polling for status
async function pollStatus() {
    try {
        const response = await fetch('/status');
        const data = await response.json();

        if (data.active) {
            // Update Canvas
            if (data.canvas) {
                const img = document.getElementById('plotter-canvas');
                img.src = 'data:image/jpeg;base64,' + data.canvas;
            }

            // Update Marker
            const marker = document.getElementById('head-marker');
            marker.style.display = 'block';

            // Scale: 10 pixels per cm
            const pixelsPerCm = 10;
            const x = data.x * pixelsPerCm;
            const y = data.y * pixelsPerCm;

            marker.style.left = x + 'px';
            marker.style.top = y + 'px';

            // Color logic: Blue if z != 0, Red otherwise (z=0)
            if (data.z !== 0) {
                marker.style.backgroundColor = 'blue';
            } else {
                marker.style.backgroundColor = 'red';
            }
        }
    } catch (error) {
        console.error("Polling error:", error);
    }
}

// Start polling
setInterval(pollStatus, 500);
