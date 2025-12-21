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
