let currentPage = 1;
let isLoading = false;
let hasMore = true;

let jobToImageMap = new Map(); // jobId -> imageId
const socket = io({ transports: ['websocket', 'polling'] });

const GALLERY_GRID = document.getElementById('galleryGrid');
const IMAGE_UPLOAD = document.getElementById('imageUpload');
const PREVIEW_BOX = document.getElementById('preview-box');
let currentDetailsImageId = null;
let scaledBlob = null;
let cardStates = new Map(); // imageId -> current slide index
let isUploading = false;

// --- Initialization ---

document.addEventListener('DOMContentLoaded', () => {
    loadImages(true);

    IMAGE_UPLOAD.addEventListener('change', handleFileSelect);

    // Preference change handler - apply to all cards instantly
    document.getElementById('preferenceSelect').addEventListener('change', () => {
        // Clear cached states so cards will recalculate with new preference
        document.querySelectorAll('.gallery-card').forEach(card => {
            const imageId = card.dataset.id;
            if (imageId && !imageId.startsWith('temp-')) {
                cardStates.delete(imageId);
                updateCardUI(imageId);
            }
        });
    });

    // Infinite Scroll
    document.querySelector('.gallery-panel').addEventListener('scroll', (e) => {
        const { scrollTop, scrollHeight, clientHeight } = e.target;
        if (scrollTop + clientHeight >= scrollHeight - 50) {
            if (hasMore && !isLoading) {
                loadImages();
            }
        }
    });

    // Start status handling via WebSockets
    socket.on('processor_jobs_update', (jobs) => {
        handleStatusUpdate(jobs);
    });

    socket.on('ai_backend_status', (data) => {
        if (!data.available) {
            showToast(`Warning: AI Backend is unreachable! ${data.error || ''}`, 'error');
        } else {
            showToast('AI Backend is back online.', 'success');
        }
    });
});

// --- File Handling ---

async function handleFileSelect(e) {
    const file = e.target.files[0];
    if (!file || isUploading) return;

    console.log('File selected:', file.name, file.size, file.type);

    try {
        isUploading = true;
        PREVIEW_BOX.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Processing...</span>';

        const bitmap = await createImageBitmap(file);
        console.log('Original dimensions:', bitmap.width, 'x', bitmap.height);

        const canvas = document.createElement('canvas');
        let width = bitmap.width;
        let height = bitmap.height;
        const maxDim = 1024;

        if (width > height) {
            if (width > maxDim) {
                height *= maxDim / width;
                width = maxDim;
            }
        } else {
            if (height > maxDim) {
                width *= maxDim / height;
                height = maxDim;
            }
        }

        width = Math.floor(width);
        height = Math.floor(height);
        console.log('Resizing to:', width, 'x', height);

        canvas.width = width;
        canvas.height = height;

        // Some Firefox versions prefer the canvas to be in the DOM
        canvas.style.position = 'fixed';
        canvas.style.left = '-10000px';
        canvas.style.top = '0';
        document.body.appendChild(canvas);

        const ctx = canvas.getContext('2d', { willReadFrequently: true });

        // Fill white background using hex
        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(0, 0, width, height);

        // Wait for Firefox to realize the canvas exists and is ready
        await new Promise(r => requestAnimationFrame(r));
        await new Promise(r => setTimeout(r, 100));

        // Draw the bitmap
        ctx.drawImage(bitmap, 0, 0, width, height);

        // Debug: Check color
        try {
            const imageData = ctx.getImageData(0, 0, 1, 1).data;
            console.log('Top-Left Pixel Color:', imageData[0], imageData[1], imageData[2], imageData[3]);
        } catch (e) {
            console.warn('Pixel check failed:', e);
        }

        canvas.toBlob(async (blob) => {
            try {
                if (blob) {
                    console.log('Scaled blob size:', blob.size);
                    scaledBlob = blob;

                    // Show preview
                    const previewUrl = URL.createObjectURL(blob);
                    PREVIEW_BOX.innerHTML = `<img src="${previewUrl}" alt="Preview">`;

                    // Auto-upload
                    await uploadAndProcess();
                }
            } catch (err) {
                console.error('Upload failed:', err);
                showToast('Upload failed', 'error');
                PREVIEW_BOX.innerHTML = '<i class="fas fa-cloud-upload-alt"></i><span>Tap to select photo</span>';
            } finally {
                isUploading = false;
                // Cleanup
                if (canvas.parentNode) document.body.removeChild(canvas);
                bitmap.close();
            }
        }, 'image/jpeg', 0.9);

    } catch (err) {
        console.error('Processing failed:', err);
        showToast('Could not process image', 'error');
        PREVIEW_BOX.innerHTML = '<i class="fas fa-cloud-upload-alt"></i><span>Tap to select photo</span>';
        isUploading = false;
    }
}

async function uploadAndProcess() {
    if (!scaledBlob) return;
    try {
        PREVIEW_BOX.innerHTML = '<i class="fas fa-spinner fa-spin"></i><span>Uploading...</span>';

        const placeholderId = 'temp-' + Date.now();
        const placeholderMeta = {
            id: placeholderId,
            original_filename: scaledBlob.name || 'Uploading...',
            upload_time: new Date().toISOString(),
            workflows: [],
            isPlaceholder: true,
            placeholderUrl: URL.createObjectURL(scaledBlob)
        };

        const placeholderCard = createImageCard(placeholderMeta);
        placeholderCard.classList.add('placeholder');
        GALLERY_GRID.prepend(placeholderCard);

        const formData = new FormData();
        formData.append('image', scaledBlob, 'upload.jpg');

        const response = await fetch('/processor/upload', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();

        if (result.status === 'ok') {
            const imageId = result.image_id;

            // Check for auto-process
            const autoProcessToggle = document.getElementById('autoProcessToggle').checked;

            if (autoProcessToggle) {
                // Process all styles in parallel with different priorities
                const styles = [
                    { name: 'clean', priority: 13 },
                    { name: 'realistic', priority: 12 },
                    { name: 'kawaii', priority: 11 },
                    { name: 'full', priority: 10 }
                ];
                const jobs = await Promise.all(styles.map(style => runWorkflow(imageId, style.name, style.priority)));

                // Register jobs and update UI
                jobs.forEach((jobId, idx) => {
                    if (jobId) {
                        jobToImageMap.set(jobId, imageId);
                    }
                });
                updateCardUI(imageId);
                showToast('All styles queued for processing!', 'success');
            }

            // Reset UI
            showToast('Image uploaded successfully!', 'success');

            // Replace the placeholder with the actual card
            const placeholder = document.querySelector(`.gallery-card[data-id="${placeholderId}"]`);
            if (placeholder) {
                placeholder.classList.remove('placeholder');
                placeholder.dataset.id = result.image_id;
                const newCard = createImageCard(result.metadata);
                placeholder.innerHTML = newCard.innerHTML;
            }

            scaledBlob = null;
            IMAGE_UPLOAD.value = '';
            PREVIEW_BOX.innerHTML = '<i class="fas fa-cloud-upload-alt"></i><span>Tap to select photo</span>';
        } else {
            showToast('Upload failed: ' + result.error, 'error');
            const placeholder = document.querySelector(`.gallery-card[data-id="${placeholderId}"]`);
            if (placeholder) placeholder.remove();
            PREVIEW_BOX.innerHTML = '<i class="fas fa-cloud-upload-alt"></i><span>Tap to select photo</span>';
        }
    } catch (err) {
        console.error(err);
        showToast('Upload failed due to network error.', 'error');
        const placeholder = document.querySelector('.gallery-card.placeholder');
        if (placeholder) placeholder.remove();
        PREVIEW_BOX.innerHTML = '<i class="fas fa-cloud-upload-alt"></i><span>Tap to select photo</span>';
    }
}

// --- Image Loading & Gallery ---

async function loadImages(reset = false) {
    if (reset) {
        currentPage = 1;
        hasMore = true;
        GALLERY_GRID.innerHTML = '';
    }

    if (isLoading || !hasMore) return;

    isLoading = true;
    document.getElementById('loadingIndicator').style.display = 'block';

    try {
        const response = await fetch(`/processor/images?page=${currentPage}&per_page=20`);
        const result = await response.json();

        if (result.images.length === 0 && currentPage === 1) {
            GALLERY_GRID.innerHTML = '<div class="empty-msg">No images found. Upload something to get started!</div>';
        }

        result.images.forEach(img => {
            const card = createImageCard(img);
            GALLERY_GRID.appendChild(card);

            img.workflows.forEach(w => {
                jobToImageMap.set(w.job_id, img.id);
            });
        });

        hasMore = result.has_more;
        if (hasMore) currentPage++;

    } catch (err) {
        console.error('Failed to load images:', err);
    } finally {
        isLoading = false;
        document.getElementById('loadingIndicator').style.display = 'none';
    }
}
async function forwardToPlotter(jobId, slug, fileHash = null) {
    try {
        console.log(`Forwarding artifact ${slug} (hash: ${fileHash}) from job ${jobId} to plotter...`);
        const response = await fetch('/processor/enqueue_to_plotter', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId, slug: slug, file_hash: fileHash })
        });
        const result = await response.json();
        console.log('Plotter response:', result);
    } catch (err) {
        console.error('Error forwarding to plotter:', err);
    }
}

function getStyles(img) {
    const stylesConfig = [
        { name: 'clean', label: 'Clean', icon: 'fa-broom' },
        { name: 'realistic', label: 'Realistic', icon: 'fa-camera' },
        { name: 'kawaii', label: 'Cute', icon: 'fa-magic' },
        { name: 'full', label: 'Full', icon: 'fa-image' }
    ];

    return stylesConfig.map(s => {
        const style = { ...s, url: '', status: 'idle', statusMessage: '' };
        // Find ALL jobs for this style and pick the "best" one
        // Priority: running > pending > completed > failed
        const styleJobs = img.workflows.filter(w => w.name === s.name);

        if (styleJobs.length > 0) {
            // Sort by a priority score
            const statusPriority = { 'running': 4, 'pending': 3, 'completed': 2, 'failed': 1 };
            const bestJob = styleJobs.sort((a, b) => statusPriority[b.status] - statusPriority[a.status])[0];

            if (bestJob.status === 'completed') {
                style.url = `/processor/artifact/${bestJob.job_id}/visualizer`;
                style.status = 'ready';
                style.job_id = bestJob.job_id;
            } else if (bestJob.status === 'pending' || bestJob.status === 'running') {
                style.status = 'processing';
                style.job_id = bestJob.job_id;
            } else {
                style.status = 'failed';
            }
        }
        return style;
    });
}

function createImageCard(img) {
    const card = document.createElement('div');
    card.className = 'gallery-card';
    card.dataset.id = img.id;

    const styles = getStyles(img);

    // Initial view selection logic:
    // 1. If we have a stored index, use it.
    // 2. Find preferred style if available (ready/processing).
    // 3. Otherwise, find the latest 'completed' or 'processing' style.
    // 4. Fallback to first available.
    if (!cardStates.has(img.id)) {
        let bestIdx = 0;
        const preference = document.getElementById('preferenceSelect').value;
        const prefIdx = styles.findIndex(s => s.name === preference);

        // Check if preferred style is available (ready or processing)
        if (prefIdx !== -1 && (styles[prefIdx].status === 'ready' || styles[prefIdx].status === 'processing')) {
            bestIdx = prefIdx;
        } else {
            // Find first completed or processing
            const priorityIdx = styles.findIndex(s => s.status === 'ready' || s.status === 'processing');
            if (priorityIdx !== -1) {
                bestIdx = priorityIdx;
            }
        }
        cardStates.set(img.id, bestIdx);
    }

    const currentIdx = cardStates.get(img.id);
    const currentStyle = styles[currentIdx] || styles[0];

    // Status Overlay Logic
    let badgeClass = '';
    let statusText = currentStyle.label;
    let tagText = '';

    if (currentStyle.status === 'ready') {
        badgeClass = 'completed';
        tagText = 'Ready';
    } else if (currentStyle.status === 'processing') {
        badgeClass = 'pending';
        tagText = 'Processing...';
    } else if (currentStyle.status === 'failed') {
        badgeClass = 'failed';
        tagText = 'Error';
    } else {
        badgeClass = 'idle';
        tagText = 'Idle';
    }

    // Image logic: always grayscale if not ready
    let thumbSrc = currentStyle.url || img.original_url || img.thumbnail || '/static/images/placeholder.jpg';
    let imgClass = '';
    if (img.isPlaceholder || currentStyle.status !== 'ready') {
        imgClass = 'uploading';
    }

    const thumbContent = `<img src="${thumbSrc}" alt="${currentStyle.label}" class="card-thumb ${imgClass}">`;

    const formattedDate = new Date(img.upload_time).toLocaleString('en-CA', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hour12: false
    }).replace(',', '');

    const isReady = currentStyle.status === 'ready';
    const isProcessing = currentStyle.status === 'processing';

    const processBtnClass = (isReady || isProcessing) ? 'btn-style disabled' : 'btn-style btn-process todo';
    const plotBtnClass = isReady ? 'btn-style btn-plot ready' : (isProcessing ? 'btn-style processing' : 'btn-style btn-plot todo');

    card.innerHTML = `
        <div class="card-header">
            <span class="date">${formattedDate}</span>
        </div>
        <div class="card-media">
            <div class="status-header ${badgeClass}">
                <span class="status-title">${statusText}</span>
                <span class="status-tag">${tagText}</span>
            </div>
            ${thumbContent}
            <div class="slideshow-nav">
                <button class="nav-arrow" onclick="cycleSlide(event, '${img.id}', -1)"><i class="fas fa-chevron-left"></i></button>
                <button class="nav-arrow" onclick="cycleSlide(event, '${img.id}', 1)"><i class="fas fa-chevron-right"></i></button>
            </div>
        </div>
        <div class="card-info">
            <div class="card-actions">
                <div class="action-row">
                    <span class="style-label">${currentStyle.label} View</span>
                    <div class="btn-group">
                        <button class="${processBtnClass}" 
                                ${isProcessing || isReady ? 'disabled' : ''} 
                                onclick="handleProcessAction(event, '${img.id}', '${currentStyle.name}')">
                            <i class="fas ${isProcessing ? 'fa-spinner fa-spin' : currentStyle.icon}"></i> 
                            ${isProcessing ? 'Queue' : (isReady ? 'Done' : 'Process')}
                        </button>
                        <button class="${plotBtnClass}" 
                                ${isProcessing ? 'disabled' : ''} 
                                onclick="handlePlotAction(event, '${img.id}', '${currentStyle.name}')">
                            <i class="fas fa-print"></i> Plot
                        </button>
                    </div>
                </div>
                <button class="btn-style btn-delete" onclick="deleteImage(event, '${img.id}')">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </div>
        </div>
    `;
    return card;
}

function cycleSlide(event, imageId, direction) {
    if (event) event.stopPropagation();
    const styles = getStyles({ id: imageId, workflows: [] }); // Dummy img to get style count
    const stylesNum = styles.length;
    let currentIdx = cardStates.get(imageId) || 0;
    currentIdx = (currentIdx + direction + stylesNum) % stylesNum;
    cardStates.set(imageId, currentIdx);

    // Efficiently re-render just the card or media part
    updateCardUI(imageId);
}

async function updateCardUI(imageId) {
    try {
        const response = await fetch(`/processor/image/${imageId}/details`);
        const img = await response.json();
        const card = document.querySelector(`.gallery-card[data-id="${imageId}"]`);
        if (card) {
            const newCard = createImageCard(img);
            card.innerHTML = newCard.innerHTML;
        }
    } catch (err) {
        console.error('Failed to update card UI:', err);
        // Optionally, remove the card if image details can't be fetched (e.g., deleted)
        const card = document.querySelector(`.gallery-card[data-id="${imageId}"]`);
        if (card) card.remove();
    }
}

async function deleteImage(event, imageId) {
    if (event) event.stopPropagation();
    if (!confirm('Are you sure you want to delete this image and all versions?')) return;
    try {
        const response = await fetch(`/processor/image/${imageId}`, { method: 'DELETE' });
        if (response.ok) {
            showToast('Image deleted.', 'success');
            loadImages(true); // Reload gallery to reflect deletion
        } else {
            const errorData = await response.json();
            showToast(`Failed to delete image: ${errorData.error}`, 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Failed to delete image due to network error.', 'error');
    }
}

async function handleProcessAction(event, imageId, style) {
    event.stopPropagation();
    const btn = event.currentTarget;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';

    await runWorkflowFromCard(imageId, style, 100); // Priority 100
}

async function handlePlotAction(event, imageId, style) {
    event.stopPropagation();
    const btn = event.currentTarget;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Plotting...';

    const details = await (await fetch(`/processor/image/${imageId}/details`)).json();
    const job = details.workflows.find(w => w.name === style && w.status === 'completed');

    if (job) {
        // If already processed, plot all slicer artifacts in order (by timestamp or hash)
        const statusResp = await fetch(`/processor/status?ids=${job.job_id}`);
        const jobsMeta = await statusResp.json();
        const artifacts = jobsMeta[0]?.artifacts || [];

        // Filter for slicers and sort by timestamp
        const slicers = artifacts
            .filter(a => a.slug.startsWith('slicer'))
            .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

        if (slicers.length > 0) {
            for (const s of slicers) {
                await forwardToPlotter(job.job_id, s.slug, s.hash);
            }
            showToast(`Sent ${slicers.length} slicer files to plotter!`, 'success');
        } else {
            showToast(`No slicer data found for ${style} version.`, 'error');
        }
    } else {
        showToast(`${style} is not ready yet. Process it first.`, 'error');
    }
    // The card will be updated by handleStatusUpdate
    updateCardUI(imageId);
}

// --- Workflow Operations ---

async function runWorkflow(imageId, workflowName, priority = 100) {
    try {
        const response = await fetch('/processor/run_workflow', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                image_id: imageId,
                workflow_name: workflowName,
                priority: priority
            })
        });
        const result = await response.json();
        if (result.status === 'ok') {
            jobToImageMap.set(result.job_id, imageId);
            return result.job_id;
        } else {
            alert('Workflow error: ' + result.error);
            return null;
        }
    } catch (err) {
        console.error(err);
        return null;
    }
}

async function runWorkflowFromCard(imageId, style, priority = 100) {
    const jobId = await runWorkflow(imageId, style, priority);
    if (jobId) {
        showToast(`${style} queued (priority ${priority}).`, 'success');
        updateCardUI(imageId); // Refresh the card to show processing status
    } else {
        showToast(`Failed to queue ${style} processing.`, 'error');
        updateCardUI(imageId); // Refresh to reset button state
    }
}

// --- Status Handling (WebSockets) ---

async function handleStatusUpdate(jobs) {
    for (const job of jobs) {
        const { job_id, status, error } = job;

        // Toast on error
        if (status === 'failed') {
            showToast(`Job ${job_id} failed: ${error || 'Unknown error'}`, 'error');
        }

        const imageId = jobToImageMap.get(job_id);
        if (imageId) {
            updateCardUI(imageId);
        }
    }
}

// --- Modal Logic --- (Removed as per instruction)

// --- Notifications ---

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    let icon = 'info-circle';
    if (type === 'success') icon = 'check-circle';
    if (type === 'error') icon = 'exclamation-circle';

    toast.innerHTML = `<i class="fas fa-${icon}"></i><span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-20px)';
        toast.style.transition = '0.5s';
        setTimeout(() => container.removeChild(toast), 500);
    }, 4000);
}

window.onclick = function (event) {
    // No modal to handle anymore
}

