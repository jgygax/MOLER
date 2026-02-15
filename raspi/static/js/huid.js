/**
 * HUID - Head-Up Interface Display
 * Mouse-only control system for VR goggle use
 */

(function() {
    'use strict';

    const state = {
        currentMode: 'camera',
        activeControl: null,
        hoveredElement: null,
        isLocked: false,
        lockSequence: [],
        targetSequence: ['L', 'R', 'R', 'L', 'R', 'L', 'L'],
        cameras: [],
        currentCameraIndex: 0,
        zoomLevel: 1.0,
        minZoom: 0.1,
        maxZoom: 10.0,
        panX: 0,
        panY: 0,
        zoomStep: 0.05,
        panStep: 30,
        frames: [],
        totalFrameCount: 0,
        currentFrameTimestamp: null,
        processedImages: [],
        currentProcessedIndex: 0,
        currentWorkflowIndex: 0,
        workflows: ['clean', 'realistic', 'kawaii', 'full'],
        autoGallery: false,
        audioEnabled: false,
        audioVoice: 'pitch_up',
        crop: { left: 0, top: 0, right: 0, bottom: 0 },
        audioSocket: null,
        audioStream: null,
        audioContext: null,
        audioWorklet: null,
        audioRecording: false,
        isFullscreen: false,
        settings: { yStart: 10, yEnd: 90 },
        db: null,
        stream: null,
        lastStoreTime: 0,
        frameId: 0,
        statusInterval: null,
        workflowCache: new Map(),
        loadingImages: new Set() // Track which images are currently loading
    };

    const elements = {};
    const DB_NAME = 'HUIDStorage';
    const DB_VERSION = 3;
    const MAX_DB_FRAMES = 1000;
    const FETCH_TIMEOUT = 15000;

    const OPTION_CONTROLS = ['scroll-workflows', 'switch-camera', 'zoom', 'pan-x', 'pan-y', 'y-start', 'y-end', 'auto-gallery', 'audio-toggle', 'audio-voice', 'crop-left', 'crop-right', 'crop-top', 'crop-bottom'];
    const ACTION_CONTROLS = ['process', 'send-plotter', 'fullscreen', 'scroll-timeline', 'scroll-images', 'reset-crop'];

    document.addEventListener('DOMContentLoaded', init);

    async function init() {
        cacheElements();
        loadSettings();
        applyYConstraints();
        await initDatabase();
        await updateTotalFrameCount();
        await enumerateCameras();
        await startCamera();
        setupEventListeners();
        startFrameCapture();
        updateUI();
        maybeStartAudio();
    }

    function cacheElements() {
        elements.video = document.getElementById('camera-video');
        elements.canvas = document.getElementById('capture-canvas');
        elements.wrapper = document.getElementById('huid-wrapper');
        elements.uiContainer = document.getElementById('ui-container');
        elements.topBar = document.getElementById('top-bar');
        elements.bottomBar = document.getElementById('bottom-bar');
        elements.overlayContainer = document.getElementById('overlay-container');
        elements.overlay = document.getElementById('overlay-image');
        elements.cropOverlay = document.getElementById('crop-overlay');
        elements.status = document.getElementById('status-text');
        elements.timelineBar = document.getElementById('timeline-bar');
        elements.timelineProgress = document.getElementById('timeline-progress');
        
        elements.modes = {
            camera: document.getElementById('mode-camera'),
            timeline: document.getElementById('mode-timeline'),
            gallery: document.getElementById('mode-gallery'),
            audio: document.getElementById('mode-audio'),
            settings: document.getElementById('mode-settings'),
            lock: document.getElementById('mode-lock')
        };
    }

    async function fetchWithTimeout(url, options = {}, timeout = FETCH_TIMEOUT) {
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), timeout);
        
        try {
            const response = await fetch(url, { ...options, signal: controller.signal });
            clearTimeout(id);
            return response;
        } catch (error) {
            clearTimeout(id);
            if (error.name === 'AbortError') throw new Error('Request timeout');
            throw error;
        }
    }

    function initDatabase() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onerror = () => reject(request.error);
            request.onsuccess = () => { state.db = request.result; resolve(); };
            request.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (db.objectStoreNames.contains('frames')) db.deleteObjectStore('frames');
                const store = db.createObjectStore('frames', { keyPath: 'id', autoIncrement: true });
                store.createIndex('timestamp', 'timestamp', { unique: false });
            };
        });
    }

    async function updateTotalFrameCount() {
        if (!state.db) return;
        return new Promise((resolve) => {
            const tx = state.db.transaction(['frames'], 'readonly');
            const store = tx.objectStore('frames');
            const request = store.count();
            request.onsuccess = () => {
                state.totalFrameCount = Math.max(request.result, state.frames.length);
                resolve();
            };
            request.onerror = () => resolve();
        });
    }

    function loadSettings() {
        const saved = localStorage.getItem('huid_settings');
        if (saved) {
            const parsed = JSON.parse(saved);
            state.settings = { ...state.settings, ...parsed.settings };
            state.currentCameraIndex = parsed.currentCameraIndex || 0;
            state.autoGallery = parsed.autoGallery || false;
            state.currentWorkflowIndex = parsed.currentWorkflowIndex || 0;
            state.audioEnabled = parsed.audioEnabled || false;
            state.audioVoice = parsed.audioVoice || 'pitch_up';
        }
    }

    function saveSettings() {
        const toSave = {
            settings: state.settings,
            currentCameraIndex: state.currentCameraIndex,
            autoGallery: state.autoGallery,
            currentWorkflowIndex: state.currentWorkflowIndex,
            audioEnabled: state.audioEnabled,
            audioVoice: state.audioVoice
        };
        localStorage.setItem('huid_settings', JSON.stringify(toSave));
    }

    function applyYConstraints() {
        document.documentElement.style.setProperty('--y-start', state.settings.yStart + '%');
        document.documentElement.style.setProperty('--y-end', state.settings.yEnd + '%');
        // Also update crop variables
        document.documentElement.style.setProperty('--crop-left', state.crop.left + '%');
        document.documentElement.style.setProperty('--crop-right', state.crop.right + '%');
        document.documentElement.style.setProperty('--crop-top', state.crop.top + '%');
        document.documentElement.style.setProperty('--crop-bottom', state.crop.bottom + '%');
    }

    async function enumerateCameras() {
        try {
            // First get permission by requesting any camera
            // This is required to get device labels
            const tempStream = await navigator.mediaDevices.getUserMedia({ video: true });
            tempStream.getTracks().forEach(t => t.stop());
            
            // Now enumerate with permission granted
            const devices = await navigator.mediaDevices.enumerateDevices();
            state.cameras = devices.filter(d => d.kind === 'videoinput');
            console.log('Found cameras:', state.cameras.map(c => ({ id: c.deviceId.slice(0, 8), label: c.label })));
        } catch (e) { console.error('Camera enumeration error:', e); }
    }

    function getCurrentCameraName() {
        const cam = state.cameras[state.currentCameraIndex];
        if (!cam) return 'Camera';
        let name = cam.label || `Cam ${state.currentCameraIndex + 1}`;
        name = name.replace(/camera|webcam|integrated/i, '').trim();
        if (!name) name = `Cam ${state.currentCameraIndex + 1}`;
        if (name.length > 12) name = name.substring(0, 10) + '..';
        return name;
    }

    async function startCamera() {
        if (state.stream) state.stream.getTracks().forEach(t => t.stop());
        try {
            const constraints = { video: { width: { ideal: 512 }, height: { ideal: 512 } } };
            
            const selectedCamera = state.cameras[state.currentCameraIndex];
            if (selectedCamera?.deviceId) {
                // Use exact deviceId if we have it
                constraints.video.deviceId = { exact: selectedCamera.deviceId };
                console.log('Starting camera:', selectedCamera.label || `Camera ${state.currentCameraIndex + 1}`, 'ID:', selectedCamera.deviceId.slice(0, 8));
            } else if (state.cameras.length > 0) {
                // Fallback: try to use facing mode for mobile
                // Front camera (selfie) usually has "user" facing mode
                // Back camera usually has "environment" facing mode
                const isFrontCamera = state.currentCameraIndex === 0;
                constraints.video.facingMode = isFrontCamera ? 'user' : 'environment';
                console.log('Using facing mode:', constraints.video.facingMode);
            }
            
            state.stream = await navigator.mediaDevices.getUserMedia(constraints);
            elements.video.srcObject = state.stream;
            console.log('Camera started successfully');
        } catch (e) { 
            console.error('Camera error:', e);
            updateStatus('Camera error: ' + e.message);
        }
    }

    function switchCamera() {
        if (state.cameras.length <= 1) {
            updateStatus('Only 1 camera found');
            return;
        }
        state.currentCameraIndex = (state.currentCameraIndex + 1) % state.cameras.length;
        const cameraName = getCurrentCameraName();
        updateStatus('Switching to: ' + cameraName);
        saveSettings();
        startCamera();
        updateUI();
    }

    function startFrameCapture() {
        const ctx = elements.canvas.getContext('2d');
        
        setInterval(() => {
            if (!elements.video.videoWidth) return;
            elements.canvas.width = 512;
            elements.canvas.height = 512;
            ctx.drawImage(elements.video, 0, 0, 512, 512);
            const dataUrl = elements.canvas.toDataURL('image/jpeg', 0.7);
            const now = Date.now();
            
            const frame = { id: ++state.frameId, timestamp: now, dataUrl };
            state.frames.unshift(frame);
            
            if (state.frames.length > 300) state.frames.pop();
            
            if (now - state.lastStoreTime >= 100) {
                storeFrame(frame);
                state.lastStoreTime = now;
                updateTotalFrameCount();
            }
            
            // Update timeline display with throttling and mode check
            if (state.currentMode === 'timeline') {
                // Only update every 100ms to reduce jitter
                if (!state.lastTimelineUpdate || now - state.lastTimelineUpdate >= 100) {
                    updateTimelineDisplay();
                    state.lastTimelineUpdate = now;
                }
            }
        }, 33);
    }

    function storeFrame(frame) {
        if (!state.db) return;
        try {
            const tx = state.db.transaction(['frames'], 'readwrite');
            const store = tx.objectStore('frames');
            store.add({ timestamp: frame.timestamp, dataUrl: frame.dataUrl }).onsuccess = () => thinOutFramesIfNeeded();
        } catch (e) { console.error('Store error:', e); }
    }

    function thinOutFramesIfNeeded() {
        if (!state.db) return;
        const tx = state.db.transaction(['frames'], 'readonly');
        const store = tx.objectStore('frames');
        store.count().onsuccess = (e) => {
            if (e.target.result > MAX_DB_FRAMES) {
                const deleteTx = state.db.transaction(['frames'], 'readwrite');
                const deleteStore = deleteTx.objectStore('frames');
                const index = deleteStore.index('timestamp');
                const cursorRequest = index.openCursor(null, 'prev');
                let position = 0;
                cursorRequest.onsuccess = (e) => {
                    const cursor = e.target.result;
                    if (cursor) {
                        if (position >= 100 && position % 2 === 1) cursor.delete();
                        position++;
                        cursor.continue();
                    }
                };
            }
        };
    }

    async function loadFramesFromDB(offset = 0, limit = 100) {
        if (!state.db) return [];
        return new Promise((resolve, reject) => {
            const tx = state.db.transaction(['frames'], 'readonly');
            const store = tx.objectStore('frames');
            const index = store.index('timestamp');
            const frames = [];
            const request = index.openCursor(null, 'prev');
            let skipped = 0, collected = 0;
            
            request.onsuccess = (e) => {
                const cursor = e.target.result;
                if (cursor && collected < limit) {
                    if (skipped < offset) {
                        skipped++;
                        cursor.continue();
                    } else {
                        frames.push({ id: cursor.value.id, timestamp: cursor.value.timestamp, dataUrl: cursor.value.dataUrl });
                        collected++;
                        cursor.continue();
                    }
                } else resolve(frames);
            };
            request.onerror = () => reject(request.error);
        });
    }

    function setupEventListeners() {
        document.addEventListener('touchstart', e => e.preventDefault(), { passive: false });
        document.addEventListener('touchmove', e => e.preventDefault(), { passive: false });
        document.addEventListener('wheel', handleWheel, { passive: false });
        document.addEventListener('mousedown', handleMouseDown);
        document.addEventListener('contextmenu', e => e.preventDefault());
        document.addEventListener('fullscreenchange', () => { state.isFullscreen = !!document.fullscreenElement; updateUI(); });
        
        // Update crop overlay on window resize
        window.addEventListener('resize', () => {
            if (state.currentMode === 'timeline') {
                setTimeout(updateCropOverlay, 100);
            }
        });
        
        // Update crop overlay when image loads
        if (elements.overlay) {
            elements.overlay.addEventListener('load', () => {
                if (state.currentMode === 'timeline') {
                    setTimeout(updateCropOverlay, 50);
                }
            });
        }
    }

    function toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(e => console.error('Fullscreen error:', e));
        } else document.exitFullscreen();
    }

    function handleWheel(e) {
        e.preventDefault();
        if (state.isLocked) return;
        const delta = e.deltaY > 0 ? 1 : -1;
        if (state.activeControl) performActiveAction(delta);
        else navigateElements(delta);
    }

    function navigateElements(delta) {
        const els = getNavigableElements();
        const currentIdx = els.indexOf(state.hoveredElement);
        let newIdx = currentIdx + delta;
        if (newIdx < 0) newIdx = els.length - 1;
        if (newIdx >= els.length) newIdx = 0;
        state.hoveredElement = els[newIdx];
        updateUI();
    }

    function getNavigableElements() {
        if (state.isLocked) return [];
        return ['camera', 'timeline', 'gallery', 'audio', 'settings', 'lock', ...getCurrentControls()];
    }

    function getCurrentControls() {
        if (state.isLocked) return [];
        switch (state.currentMode) {
            case 'camera': return ['zoom', 'pan-x', 'pan-y', 'switch-camera'];
            case 'timeline': return ['scroll-timeline', 'crop-left', 'crop-right', 'crop-top', 'crop-bottom', 'reset-crop', 'process', 'auto-gallery'];
            case 'gallery': return ['scroll-images', 'scroll-workflows', 'send-plotter'];
            case 'audio': return ['audio-toggle', 'audio-voice'];
            case 'settings': return ['y-start', 'y-end', 'fullscreen'];
            default: return [];
        }
    }

    function handleMouseDown(e) {
        e.preventDefault();
        if (state.isLocked) { checkLockSequence(e.button === 0 ? 'L' : 'R'); return; }
        if (e.button === 0) handleLeftClick();
        else if (e.button === 2) handleRightClick();
    }

    function formatTimeAgo(timestamp) {
        const seconds = Math.floor((Date.now() - timestamp) / 1000);
        if (seconds < 60) return `${seconds}s ago`;
        if (seconds < 3600) {
            const m = Math.floor(seconds / 60), s = seconds % 60;
            return s > 0 ? `${m}m ${s}s ago` : `${m}m ago`;
        }
        const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
        return m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
    }

    function getFrameAgeColor(timestamp) {
        const ageMs = Date.now() - timestamp, maxAge = 3600000;
        if (ageMs < 10000) {
            const t = ageMs / 10000, r = Math.round(0 + t * 170), g = 255, b = 0;
            return `rgb(${r}, ${g}, ${b})`;
        } else if (ageMs < 60000) {
            const t = (ageMs - 10000) / 50000, r = 170 + Math.round(t * 85), g = 255 - Math.round(t * 85), b = 0;
            return `rgb(${r}, ${g}, ${b})`;
        } else if (ageMs < maxAge) {
            const t = (ageMs - 60000) / (maxAge - 60000);
            if (t < 0.5) {
                const localT = t * 2, r = 255, g = 170 - Math.round(localT * 170), b = 0;
                return `rgb(${r}, ${g}, ${b})`;
            } else {
                const localT = (t - 0.5) * 2, r = 255 - Math.round(localT * 85), g = 0, b = Math.round(localT * 255);
                return `rgb(${r}, ${g}, ${b})`;
            }
        }
        return '#aa00ff';
    }

    function startStatusUpdates() {
        if (state.statusInterval) clearInterval(state.statusInterval);
        state.statusInterval = setInterval(() => {
            if (state.currentMode === 'timeline' && state.currentFrameTimestamp) {
                updateStatus(formatTimeAgo(state.currentFrameTimestamp));
                const frame = state.frames.find(f => f.timestamp === state.currentFrameTimestamp);
                if (frame && elements.timelineProgress) {
                    elements.timelineProgress.style.backgroundColor = getFrameAgeColor(frame.timestamp);
                }
            }
        }, 1000);
    }

    function stopStatusUpdates() {
        if (state.statusInterval) {
            clearInterval(state.statusInterval);
            state.statusInterval = null;
        }
    }

    function getLockStatusText() {
        const entered = state.lockSequence.join('');
        const remaining = state.targetSequence.slice(state.lockSequence.length).join('');
        return `${entered}[${remaining}]`;
    }

    function checkLockSequence(input) {
        const expected = state.targetSequence[state.lockSequence.length];
        if (input !== expected) {
            state.lockSequence = [];
            updateStatus(getLockStatusText());
            return;
        }
        state.lockSequence.push(input);
        if (state.lockSequence.length === state.targetSequence.length) {
            state.isLocked = false;
            state.lockSequence = [];
            state.currentMode = 'camera';
            state.hoveredElement = 'camera';
            elements.wrapper.classList.remove('locked');
            updateStatus('Unlocked!');
            updateUI();
        } else updateStatus(getLockStatusText());
    }

    function handleLeftClick() {
        const el = state.hoveredElement;
        if (!el) return;
        
        if (['camera', 'timeline', 'gallery', 'audio', 'settings', 'lock'].includes(el)) {
            if (state.activeControl) state.activeControl = null;
            
            if (el === 'lock') {
                state.isLocked = true;
                state.currentMode = 'lock';
                state.lockSequence = [];
                elements.wrapper.classList.add('locked');
                updateStatus(getLockStatusText());
                stopStatusUpdates();
                updateUI();
                return;
            }
            
            if ((state.currentMode === 'gallery' || state.currentMode === 'timeline') && el !== state.currentMode) {
                hideOverlay();
            }
            
            state.currentMode = el;
            const controls = getCurrentControls();
            if (controls.length > 0) {
                state.hoveredElement = controls[0];
                if (el === 'timeline' && controls[0] === 'scroll-timeline') {
                    state.activeControl = 'scroll-timeline';
                    showTimeline();
                } else if (el === 'gallery' && controls[0] === 'scroll-images') {
                    state.activeControl = 'scroll-images';
                    showGallery();
                }
            } else state.hoveredElement = el;
            
            if (el === 'timeline' && state.activeControl !== 'scroll-timeline') showTimeline();
            else if (el === 'gallery' && state.activeControl !== 'scroll-images') showGallery();
            else if (el === 'camera') {
                hideOverlay();
                stopStatusUpdates();
            }
            
            updateUI();
            return;
        }
        
        if (state.activeControl === el) state.activeControl = null;
        else {
            state.activeControl = el;
            if (el === 'process') processFrame();
            if (el === 'send-plotter') sendToPlotter();
            if (el === 'switch-camera') switchCamera();
            if (el === 'auto-gallery') { 
                state.autoGallery = !state.autoGallery; 
                saveSettings();
                state.activeControl = null; 
            }
            if (el === 'fullscreen') toggleFullscreen();
        }
        updateUI();
    }

    function handleRightClick() {
        if (state.activeControl) { state.activeControl = null; updateUI(); }
    }

    function performActiveAction(delta) {
        const scrollMultiplier = (state.activeControl === 'scroll-timeline') ? 5 : 1;
        const effectiveDelta = delta * scrollMultiplier;
        
        switch (state.activeControl) {
            case 'zoom':
                state.zoomLevel += delta * state.zoomStep;
                state.zoomLevel = Math.max(state.minZoom, Math.min(state.maxZoom, state.zoomLevel));
                updateCameraTransform();
                updateStatus(`Zoom: ${state.zoomLevel.toFixed(1)}x`);
                break;
            case 'pan-x': 
                state.panX += delta * state.panStep; 
                updateCameraTransform(); 
                updateStatus(`Pan X: ${state.panX}px`);
                break;
            case 'pan-y': 
                state.panY += delta * state.panStep; 
                updateCameraTransform(); 
                updateStatus(`Pan Y: ${state.panY}px`);
                break;
            case 'scroll-timeline': scrollTimeline(effectiveDelta); break;
            case 'scroll-images': scrollGallery(delta); break;
            case 'scroll-workflows': 
                scrollWorkflows(delta); 
                saveSettings();
                break;
            case 'y-start':
                state.settings.yStart = Math.max(0, Math.min(80, state.settings.yStart + delta));
                saveSettings(); 
                applyYConstraints(); 
                break;
            case 'y-end':
                state.settings.yEnd = Math.max(20, Math.min(100, state.settings.yEnd + delta));
                saveSettings(); 
                applyYConstraints(); 
                break;
            case 'audio-toggle':
                state.audioEnabled = !state.audioEnabled;
                saveSettings();
                if (state.audioEnabled) {
                    startAudioStream();
                } else {
                    stopAudioStream();
                }
                break;
            case 'audio-voice':
                const voices = ['pitch_up'];
                const currentIndex = voices.indexOf(state.audioVoice);
                state.audioVoice = voices[(currentIndex + 1) % voices.length];
                saveSettings();
                if (state.audioRecording) {
                    changeAudioVoice(state.audioVoice);
                }
                break;
            case 'crop-left':
                state.crop.left = Math.max(0, Math.min(90 - state.crop.right, state.crop.left + delta * 2));
                updateCropOverlay();
                updateStatus(`Crop L: ${state.crop.left}%`);
                break;
            case 'crop-right':
                state.crop.right = Math.max(0, Math.min(90 - state.crop.left, state.crop.right + delta * 2));
                updateCropOverlay();
                updateStatus(`Crop R: ${state.crop.right}%`);
                break;
            case 'crop-top':
                state.crop.top = Math.max(0, Math.min(90 - state.crop.bottom, state.crop.top + delta * 2));
                updateCropOverlay();
                updateStatus(`Crop T: ${state.crop.top}%`);
                break;
            case 'crop-bottom':
                state.crop.bottom = Math.max(0, Math.min(90 - state.crop.top, state.crop.bottom + delta * 2));
                updateCropOverlay();
                updateStatus(`Crop B: ${state.crop.bottom}%`);
                break;
            case 'reset-crop':
                state.crop = { left: 0, top: 0, right: 0, bottom: 0 };
                updateCropOverlay();
                state.activeControl = null;
                break;
        }
        updateUI();
    }

    function updateCameraTransform() {
        elements.video.style.transform = `translate(calc(-50% + ${-state.panX}px), calc(-50% + ${-state.panY}px)) scale(${state.zoomLevel})`;
    }

    function getCurrentFrameIndex() {
        if (!state.currentFrameTimestamp) return 0;
        if (state.frames.length === 0) return 0;
        
        // Find by exact timestamp match first
        const exactIdx = state.frames.findIndex(f => f.timestamp === state.currentFrameTimestamp);
        if (exactIdx >= 0) return exactIdx;
        
        // If exact match not found (frame may have been thinned out), find closest
        let closestIdx = 0;
        let minDiff = Infinity;
        
        for (let i = 0; i < state.frames.length; i++) {
            const diff = Math.abs(state.frames[i].timestamp - state.currentFrameTimestamp);
            if (diff < minDiff) {
                minDiff = diff;
                closestIdx = i;
            }
        }
        
        // Update the timestamp to match what we found
        state.currentFrameTimestamp = state.frames[closestIdx].timestamp;
        return closestIdx;
    }

    function updateTimelineDisplay() {
        if (!elements.timelineProgress) return;
        if (state.totalFrameCount === 0 || state.frames.length === 0) {
            elements.timelineProgress.style.width = '0%';
            return;
        }
        
        const currentIdx = getCurrentFrameIndex();
        // Use the larger of total count or frames length for calculation
        const totalCount = Math.max(state.totalFrameCount, state.frames.length);
        const progress = totalCount > 1 ? (currentIdx / (totalCount - 1)) * 100 : 0;
        elements.timelineProgress.style.width = `${Math.min(progress, 100)}%`;
        
        const frame = state.frames[currentIdx];
        if (frame) {
            elements.timelineProgress.style.backgroundColor = getFrameAgeColor(frame.timestamp);
        }
    }

    async function showTimeline() {
        if (state.frames.length === 0) {
            const dbFrames = await loadFramesFromDB(0, 100);
            state.frames = dbFrames;
        }
        
        if (state.frames.length > 0) {
            state.currentFrameTimestamp = state.frames[0].timestamp;
            const frame = state.frames[0];
            elements.overlay.src = frame.dataUrl;
            showOverlay();
            elements.overlay.style.filter = 'none';
            if (elements.timelineBar) elements.timelineBar.classList.add('visible');
            // Wait for image to load before updating crop overlay
            requestAnimationFrame(() => {
                setTimeout(updateCropOverlay, 100);
            });
            updateTimelineDisplay();
            updateStatus(formatTimeAgo(frame.timestamp));
            startStatusUpdates();
        }
    }

    async function scrollTimeline(delta) {
        if (state.frames.length === 0) return;
        const currentIdx = getCurrentFrameIndex();
        const newIndex = currentIdx + delta;
        
        if (newIndex >= state.frames.length - 10) {
            const moreFrames = await loadFramesFromDB(state.frames.length, 50);
            if (moreFrames.length > 0) state.frames = state.frames.concat(moreFrames);
        }
        
        const clampedIndex = Math.max(0, Math.min(state.frames.length - 1, newIndex));
        const frame = state.frames[clampedIndex];
        state.currentFrameTimestamp = frame.timestamp;
        elements.overlay.src = frame.dataUrl;
        showOverlay();
        elements.overlay.style.filter = 'none';
        // Wait for image to load before updating crop overlay
        requestAnimationFrame(() => {
            setTimeout(updateCropOverlay, 100);
        });
        updateTimelineDisplay();
        updateStatus(formatTimeAgo(frame.timestamp));
    }

    async function showGallery() {
        await loadProcessedImages();
        if (state.processedImages.length > 0) {
            state.currentProcessedIndex = 0;
            showCurrentWorkflowImage();
        } else updateStatus('No processed images');
    }

    // Show image immediately, then load workflow details async
    function showCurrentWorkflowImage() {
        const img = state.processedImages[state.currentProcessedIndex];
        if (!img) return;
        
        const workflow = state.workflows[state.currentWorkflowIndex];
        const cacheKey = `${img.id}-${workflow}`;
        const timeAgo = img.timestamp ? formatTimeAgo(img.timestamp) : '';
        const statusPrefix = timeAgo ? `[${timeAgo}] ` : '';
        
        // Show fallback immediately (thumbnail/original in B&W)
        showOverlay();
        elements.overlay.src = img.thumbnail || img.original_url;
        elements.overlay.style.filter = 'grayscale(1) brightness(0.7)';
        hideCropOverlay();
        
        // Handle temp images with local workflow data
        if (img.isTemp) {
            const wfData = img.workflows?.find(w => w.name === workflow);
            if (img.uploadStatus === 'uploading') {
                updateStatus(`${statusPrefix}Uploading...`);
            } else if (img.uploadStatus === 'failed') {
                updateStatus(`${statusPrefix}Upload failed`);
                elements.overlay.style.filter = 'grayscale(1) brightness(0.4)';
            } else if (wfData) {
                if (wfData.status === 'pending') {
                    updateStatus(`${statusPrefix}${workflow}: Waiting...`);
                } else if (wfData.status === 'starting') {
                    updateStatus(`${statusPrefix}${workflow}: Starting...`);
                } else if (wfData.status === 'processing') {
                    updateStatus(`${statusPrefix}${workflow}: Processing...`);
                } else if (wfData.status === 'failed' || wfData.status === 'error') {
                    updateStatus(`${statusPrefix}${workflow}: Failed`);
                    elements.overlay.style.filter = 'grayscale(1) brightness(0.4)';
                } else if (wfData.status === 'completed' && wfData.job_id) {
                    elements.overlay.src = `/processor/artifact/${wfData.job_id}/visualizer`;
                    elements.overlay.style.filter = 'none';
                    updateStatus(`${statusPrefix}${workflow}: Ready`);
                }
            }
            return;
        }
        
        updateStatus(`${statusPrefix}${workflow}: Loading...`);
        
        // Check cache first - if cached and ready, show immediately
        if (state.workflowCache.has(cacheKey)) {
            const cached = state.workflowCache.get(cacheKey);
            if (cached.status === 'ready' && cached.url) {
                elements.overlay.src = cached.url;
                elements.overlay.style.filter = 'none';
                updateStatus(`${statusPrefix}${workflow}: Ready`);
                return;
            }
        }
        
        // Skip if already loading this combo
        if (state.loadingImages.has(cacheKey)) return;
        
        // Start async load in background
        loadWorkflowDetailsAsync(img, workflow, cacheKey);
    }

    // Async background loader
    async function loadWorkflowDetailsAsync(img, workflow, cacheKey) {
        state.loadingImages.add(cacheKey);
        const timeAgo = img.timestamp ? formatTimeAgo(img.timestamp) : '';
        const statusPrefix = timeAgo ? `[${timeAgo}] ` : '';
        
        try {
            const res = await fetchWithTimeout(`/processor/image/${img.id}/details`, {}, FETCH_TIMEOUT);
            if (!res.ok) throw new Error('Failed to fetch details');
            
            const details = await res.json();
            const workflowData = details.workflows?.find(w => w.name === workflow);
            
            // Check if user is still viewing this image/workflow
            const currentImg = state.processedImages[state.currentProcessedIndex];
            const currentWorkflow = state.workflows[state.currentWorkflowIndex];
            const stillRelevant = currentImg?.id === img.id && currentWorkflow === workflow;
            
            if (!workflowData) {
                state.workflowCache.set(cacheKey, { status: 'idle', url: null });
                if (stillRelevant) {
                    updateStatus(`${statusPrefix}${workflow}: Not processed`);
                }
                return;
            }
            
            state.workflowCache.set(cacheKey, {
                status: workflowData.status,
                url: workflowData.job_id ? `/processor/artifact/${workflowData.job_id}/visualizer` : null
            });
            
            if (!stillRelevant) return;
            
            if (workflowData.status === 'completed' && workflowData.job_id) {
                elements.overlay.src = `/processor/artifact/${workflowData.job_id}/visualizer`;
                elements.overlay.style.filter = 'none';
                updateStatus(`${statusPrefix}${workflow}: Ready`);
            } else if (workflowData.status === 'processing' || workflowData.status === 'pending') {
                updateStatus(`${statusPrefix}${workflow}: Processing...`);
            } else if (workflowData.status === 'failed' || workflowData.status === 'error') {
                elements.overlay.style.filter = 'grayscale(1) brightness(0.5)';
                updateStatus(`${statusPrefix}${workflow}: Error`);
            } else {
                updateStatus(`${statusPrefix}${workflow}: ${workflowData.status || 'Unknown'}`);
            }
        } catch (e) {
            console.error('Failed to fetch workflow details:', e);
            // Only update status if still viewing this image
            const currentImg = state.processedImages[state.currentProcessedIndex];
            const currentWorkflow = state.workflows[state.currentWorkflowIndex];
            if (currentImg?.id === img.id && currentWorkflow === workflow) {
                updateStatus(`${statusPrefix}${workflow}: Unavailable`);
            }
        } finally {
            state.loadingImages.delete(cacheKey);
        }
    }

    function scrollGallery(delta) {
        if (state.processedImages.length === 0) return;
        state.currentProcessedIndex += delta;
        if (state.currentProcessedIndex < 0) state.currentProcessedIndex = 0;
        if (state.currentProcessedIndex >= state.processedImages.length) state.currentProcessedIndex = state.processedImages.length - 1;
        showCurrentWorkflowImage();
    }

    function scrollWorkflows(delta) {
        if (state.processedImages.length === 0) return;
        state.currentWorkflowIndex += delta;
        if (state.currentWorkflowIndex < 0) state.currentWorkflowIndex = state.workflows.length - 1;
        if (state.currentWorkflowIndex >= state.workflows.length) state.currentWorkflowIndex = 0;
        showCurrentWorkflowImage();
        saveSettings();
    }

    function hideOverlay() {
        if (elements.overlayContainer) elements.overlayContainer.classList.remove('visible');
        if (elements.timelineBar) elements.timelineBar.classList.remove('visible');
        hideCropOverlay();
        updateStatus('');
    }

    function showOverlay() {
        if (elements.overlayContainer) elements.overlayContainer.classList.add('visible');
    }

    function updateCropOverlay() {
        if (!elements.cropOverlay || !elements.overlay) return;
        
        const hasCrop = state.crop.left > 0 || state.crop.right > 0 || state.crop.top > 0 || state.crop.bottom > 0;
        
        // Show crop overlay in timeline mode (where we process images)
        if (hasCrop && state.currentMode === 'timeline') {
            // Get the actual displayed image rectangle
            const imgRect = elements.overlay.getBoundingClientRect();
            const containerRect = elements.overlayContainer.getBoundingClientRect();
            
            // Position crop overlay to match the actual displayed image
            const overlayStyle = elements.cropOverlay.style;
            overlayStyle.display = 'block';
            overlayStyle.left = (imgRect.left - containerRect.left) + 'px';
            overlayStyle.top = (imgRect.top - containerRect.top) + 'px';
            overlayStyle.width = imgRect.width + 'px';
            overlayStyle.height = imgRect.height + 'px';
            
            // Calculate crop display positions based on percentages
            const cropTopPx = (state.crop.top / 100) * imgRect.height;
            const cropBottomPx = (state.crop.bottom / 100) * imgRect.height;
            const cropLeftPx = (state.crop.left / 100) * imgRect.width;
            const cropRightPx = (state.crop.right / 100) * imgRect.width;
            
            // Update CSS variables for the overlay
            elements.cropOverlay.style.setProperty('--crop-top-display', cropTopPx + 'px');
            elements.cropOverlay.style.setProperty('--crop-bottom-display', cropBottomPx + 'px');
            elements.cropOverlay.style.setProperty('--crop-left-display', cropLeftPx + 'px');
            elements.cropOverlay.style.setProperty('--crop-right-display', cropRightPx + 'px');
            
            console.log('Crop overlay positioned:', {
                imageSize: `${imgRect.width}x${imgRect.height}`,
                crop: state.crop,
                pixels: { top: cropTopPx, bottom: cropBottomPx, left: cropLeftPx, right: cropRightPx }
            });
        } else {
            hideCropOverlay();
        }
    }

    function hideCropOverlay() {
        if (!elements.cropOverlay) return;
        elements.cropOverlay.style.display = 'none';
    }

    async function processFrame() {
        if (state.frames.length === 0) return;
        const frameIdx = getCurrentFrameIndex();
        const frame = state.frames[frameIdx] || state.frames[0];
        
        // Check if crop is applied
        const hasCrop = state.crop.left > 0 || state.crop.right > 0 || state.crop.top > 0 || state.crop.bottom > 0;
        
        // Generate a temporary ID for immediate display
        const tempId = 'temp_' + Date.now();
        const tempImage = {
            id: tempId,
            timestamp: Date.now(),
            original_url: frame.dataUrl,
            thumbnail: frame.dataUrl,
            isTemp: true,
            uploadStatus: 'uploading',
            workflows: state.workflows.map(w => ({ name: w, status: 'pending' }))
        };
        
        // Add to gallery immediately
        state.processedImages.unshift(tempImage);
        state.currentProcessedIndex = 0;
        
        // Switch to gallery immediately if auto-gallery is on
        if (state.autoGallery) {
            state.currentMode = 'gallery';
            state.hoveredElement = 'scroll-images';
            state.activeControl = 'scroll-images';
            // Show the temp image directly without reloading from backend
            showCurrentWorkflowImage();
            updateUI();
        }
        
        const timeAgo = formatTimeAgo(tempImage.timestamp);
        const statusPrefix = `[${timeAgo}] `;
        updateStatus(`${statusPrefix}Uploading...`);
        
        // Do all backend operations asynchronously
        (async () => {
            try {
                // Always send the original image - let the server handle cropping
                const blob = await fetch(frame.dataUrl).then(r => r.blob());
                
                const formData = new FormData();
                formData.append('image', blob, 'frame.jpg');
                
                // Send crop coordinates to server if applied
                if (hasCrop) {
                    console.log('Sending crop coordinates:', state.crop);
                    updateStatus(`${statusPrefix}Uploading with crop...`);
                    formData.append('crop_left', state.crop.left);
                    formData.append('crop_top', state.crop.top);
                    formData.append('crop_right', state.crop.right);
                    formData.append('crop_bottom', state.crop.bottom);
                }
                
                const uploadRes = await fetchWithTimeout('/processor/upload', { method: 'POST', body: formData }, FETCH_TIMEOUT);
                const uploadData = await uploadRes.json();
                
                if (uploadData.status === 'ok' || uploadData.success) {
                    const imageId = uploadData.image_id;
                    
                    // Update the temp image with real ID
                    tempImage.id = imageId;
                    tempImage.isTemp = false;
                    tempImage.uploadStatus = 'uploaded';
                    
                    // Update gallery if we're viewing this image
                    if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                        showCurrentWorkflowImage();
                    }
                    
                    updateStatus(`${statusPrefix}Uploaded`);
                    
                    // Start workflows one by one, updating status as they start
                    for (const workflow of state.workflows) {
                        try {
                            // Update status to show which workflow is starting
                            const wfEntry = tempImage.workflows.find(w => w.name === workflow);
                            if (wfEntry) wfEntry.status = 'starting';
                            
                            if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                                updateStatus(`${statusPrefix}${workflow}: Starting...`);
                            }
                            
                            const response = await fetchWithTimeout('/processor/run_workflow', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ image_id: imageId, workflow_name: workflow })
                            }, FETCH_TIMEOUT);
                            
                            const result = await response.json();
                            if (result.job_id) {
                                if (wfEntry) {
                                    wfEntry.job_id = result.job_id;
                                    wfEntry.status = 'processing';
                                }
                                
                                // Update cache
                                const cacheKey = `${imageId}-${workflow}`;
                                state.workflowCache.set(cacheKey, {
                                    status: 'processing',
                                    url: null,
                                    job_id: result.job_id
                                });
                            }
                        } catch (e) {
                            console.error(`Workflow ${workflow} failed to start:`, e);
                            const wfEntry = tempImage.workflows.find(w => w.name === workflow);
                            if (wfEntry) wfEntry.status = 'failed';
                        }
                    }
                    
                    if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                        updateStatus(`${statusPrefix}All workflows started`);
                    }
                    
                    // Now poll for workflow completion one by one
                    pollWorkflowCompletion(tempImage);
                }
            } catch (e) { 
                console.error('Upload failed:', e);
                tempImage.uploadStatus = 'failed';
                if (state.currentMode === 'gallery' && state.currentProcessedIndex === 0) {
                    updateStatus(`${statusPrefix}Upload failed`);
                }
            }
        })();
    }
    
    // Poll for workflow completion status
    async function pollWorkflowCompletion(imageEntry) {
        const checkInterval = 5000; // Check every 5 seconds
        const maxAttempts = 60; // Max 5 minutes
        let attempts = 0;
        
        const checkWorkflows = async () => {
            if (attempts >= maxAttempts) return;
            attempts++;
            
            try {
                const res = await fetchWithTimeout(`/processor/image/${imageEntry.id}/details`, {}, FETCH_TIMEOUT);
                if (!res.ok) return;
                
                const details = await res.json();
                
                for (const workflow of imageEntry.workflows) {
                    if (workflow.status === 'completed' || workflow.status === 'failed') continue;
                    
                    const backendWorkflow = details.workflows?.find(w => w.name === workflow.name);
                    if (backendWorkflow) {
                        workflow.status = backendWorkflow.status;
                        workflow.job_id = backendWorkflow.job_id;
                        
                        // Update cache
                        const cacheKey = `${imageEntry.id}-${workflow.name}`;
                        state.workflowCache.set(cacheKey, {
                            status: backendWorkflow.status,
                            url: backendWorkflow.job_id ? `/processor/artifact/${backendWorkflow.job_id}/visualizer` : null,
                            job_id: backendWorkflow.job_id
                        });
                        
                        // Update display if viewing this image
                        if (state.currentMode === 'gallery' && 
                            state.processedImages[state.currentProcessedIndex]?.id === imageEntry.id &&
                            state.workflows[state.currentWorkflowIndex] === workflow.name) {
                            showCurrentWorkflowImage();
                        }
                    }
                }
                
                // Check if all workflows are done
                const allDone = imageEntry.workflows.every(w => 
                    w.status === 'completed' || w.status === 'failed' || w.status === 'error'
                );
                
                if (!allDone) {
                    setTimeout(checkWorkflows, checkInterval);
                }
            } catch (e) {
                console.error('Workflow status check failed:', e);
                setTimeout(checkWorkflows, checkInterval);
            }
        };
        
        setTimeout(checkWorkflows, checkInterval);
    }

    async function loadProcessedImages() {
        try {
            const res = await fetchWithTimeout('/processor/images', {}, FETCH_TIMEOUT);
            const data = await res.json();
            state.processedImages = data.images || [];
        } catch (e) { 
            console.error('Load error:', e);
            state.processedImages = [];
        }
    }

    async function sendToPlotter() {
        const img = state.processedImages[state.currentProcessedIndex];
        if (!img) return;
        
        const workflow = state.workflows[state.currentWorkflowIndex];
        updateStatus('Getting job info...');
        
        // Check if we need to apply crop
        const hasCrop = state.crop.left > 0 || state.crop.right > 0 || state.crop.top > 0 || state.crop.bottom > 0;
        
        try {
            // Get job_id from cache or fetch from backend
            const cacheKey = `${img.id}-${workflow}`;
            let jobId = null;
            
            if (state.workflowCache.has(cacheKey)) {
                const cached = state.workflowCache.get(cacheKey);
                jobId = cached.job_id;
            }
            
            // If not in cache, fetch details
            if (!jobId) {
                const res = await fetchWithTimeout(`/processor/image/${img.id}/details`, {}, FETCH_TIMEOUT);
                if (res.ok) {
                    const details = await res.json();
                    const wfData = details.workflows?.find(w => w.name === workflow);
                    if (wfData) {
                        jobId = wfData.job_id;
                        // Update cache
                        state.workflowCache.set(cacheKey, {
                            status: wfData.status,
                            url: wfData.job_id ? `/processor/artifact/${wfData.job_id}/visualizer` : null,
                            job_id: wfData.job_id
                        });
                    }
                }
            }
            
            if (!jobId) {
                updateStatus('No job found');
                return;
            }
            
            updateStatus('Getting artifacts...');
            
            // Fetch status to get artifacts with file_hash (like processor.js does)
            const statusRes = await fetchWithTimeout(`/processor/status?ids=${jobId}`, {}, FETCH_TIMEOUT);
            if (!statusRes.ok) {
                updateStatus('Failed to get artifacts');
                return;
            }
            
            const jobsMeta = await statusRes.json();
            const artifacts = jobsMeta[0]?.artifacts || [];
            
            // Filter for slicers and sort by timestamp
            const slicers = artifacts
                .filter(a => a.slug && a.slug.startsWith('slicer'))
                .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
            
            if (slicers.length === 0) {
                updateStatus('No slicer data found');
                return;
            }
            
            updateStatus('Sending to plotter...');
            
            // Send each slicer file to plotter
            for (const s of slicers) {
                await fetchWithTimeout('/processor/enqueue_to_plotter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        job_id: jobId, 
                        slug: s.slug, 
                        file_hash: s.hash 
                    })
                }, FETCH_TIMEOUT);
            }
            
            // If crop is applied, fetch and crop the visualizer image first
            if (hasCrop && slicers.length > 0) {
                updateStatus('Applying crop...');
                try {
                    const visualizerUrl = `/processor/artifact/${jobId}/visualizer`;
                    const croppedBlob = await cropImage(visualizerUrl, state.crop);
                    
                    // Upload the cropped image as a new image
                    const formData = new FormData();
                    formData.append('image', croppedBlob, 'cropped.jpg');
                    
                    const uploadRes = await fetchWithTimeout('/processor/upload', { 
                        method: 'POST', 
                        body: formData 
                    }, FETCH_TIMEOUT);
                    
                    const uploadData = await uploadRes.json();
                    if (uploadData.status === 'ok' || uploadData.success) {
                        // Run the same workflow on the cropped image
                        const workflowRes = await fetchWithTimeout('/processor/run_workflow', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ 
                                image_id: uploadData.image_id, 
                                workflow_name: workflow 
                            })
                        }, FETCH_TIMEOUT);
                        
                        const workflowResult = await workflowRes.json();
                        if (workflowResult.job_id) {
                            // Wait a moment for processing to start
                            await new Promise(resolve => setTimeout(resolve, 2000));
                            
                            // Get the new job's slicers
                            const newStatusRes = await fetchWithTimeout(`/processor/status?ids=${workflowResult.job_id}`, {}, FETCH_TIMEOUT);
                            const newJobsMeta = await newStatusRes.json();
                            const newArtifacts = newJobsMeta[0]?.artifacts || [];
                            const newSlicers = newArtifacts
                                .filter(a => a.slug && a.slug.startsWith('slicer'))
                                .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
                            
                            // Send the new cropped slicers instead
                            for (const s of newSlicers) {
                                await fetchWithTimeout('/processor/enqueue_to_plotter', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ 
                                        job_id: workflowResult.job_id, 
                                        slug: s.slug, 
                                        file_hash: s.hash 
                                    })
                                }, FETCH_TIMEOUT);
                            }
                            
                            updateStatus(`Sent ${newSlicers.length} cropped file(s) to plotter`);
                            state.activeControl = null;
                            updateUI();
                            return;
                        }
                    }
                } catch (cropError) {
                    console.error('Crop error:', cropError);
                    updateStatus('Crop failed, sending original...');
                }
            }
            
            updateStatus(`Sent ${slicers.length} file(s) to plotter`);
            state.activeControl = null;
            updateUI();
        } catch (e) { 
            updateStatus('Plot error'); 
            console.error(e);
        }
    }

    async function cropImage(imageUrl, crop) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                
                // Calculate crop coordinates
                const cropX = Math.round((crop.left / 100) * img.width);
                const cropY = Math.round((crop.top / 100) * img.height);
                const cropWidth = Math.round(img.width - ((crop.left + crop.right) / 100) * img.width);
                const cropHeight = Math.round(img.height - ((crop.top + crop.bottom) / 100) * img.height);
                
                canvas.width = cropWidth;
                canvas.height = cropHeight;
                
                ctx.drawImage(img, cropX, cropY, cropWidth, cropHeight, 0, 0, cropWidth, cropHeight);
                
                canvas.toBlob((blob) => {
                    if (blob) resolve(blob);
                    else reject(new Error('Canvas toBlob failed'));
                }, 'image/jpeg', 0.9);
            };
            img.onerror = () => reject(new Error('Failed to load image'));
            img.src = imageUrl;
        });
    }

    function updateStatus(text) { elements.status.textContent = text; }

    function updateUI() {
        Object.keys(elements.modes).forEach(mode => {
            const btn = elements.modes[mode];
            if (!btn) return;
            const isActive = mode === state.currentMode;
            const isHovered = mode === state.hoveredElement;
            btn.classList.remove('blue', 'green');
            if (isActive) btn.classList.add('green');
            if (isHovered && !state.activeControl) btn.classList.add('blue');
        });
        
        elements.bottomBar.innerHTML = '';
        const controls = getCurrentControls();
        controls.forEach(control => {
            const btn = document.createElement('button');
            btn.className = 'control-btn';
            btn.innerHTML = formatLabel(control);
            const isActive = control === state.activeControl;
            const isHovered = control === state.hoveredElement;
            
            if (isHovered && !state.activeControl) {
                if (OPTION_CONTROLS.includes(control)) btn.classList.add('yellow');
                else if (ACTION_CONTROLS.includes(control)) btn.classList.add('red');
                else btn.classList.add('blue');
            }
            if (isActive) btn.classList.add('green');
            elements.bottomBar.appendChild(btn);
        });
        
        if (elements.timelineBar && state.currentMode !== 'timeline') {
            elements.timelineBar.classList.remove('visible');
        }
    }

    function formatLabel(control) {
        const labels = {
            'zoom': `<i class="fas fa-search-plus"></i> ${state.zoomLevel.toFixed(1)}x`,
            'pan-x': `<i class="fas fa-arrows-alt-h"></i> ${state.panX}`,
            'pan-y': `<i class="fas fa-arrows-alt-v"></i> ${state.panY}`,
            'switch-camera': `<i class="fas fa-video"></i> ${getCurrentCameraName()}`,
            'scroll-timeline': '<i class="fas fa-scroll"></i> Scroll',
            'process': '<i class="fas fa-magic"></i> Process',
            'auto-gallery': `<i class="fas fa-sync"></i> ${state.autoGallery ? 'ON' : 'OFF'}`,
            'scroll-images': '<i class="fas fa-images"></i> Img',
            'scroll-workflows': `<i class="fas fa-palette"></i> ${state.workflows[state.currentWorkflowIndex] || 'Style'}`,
            'send-plotter': '<i class="fas fa-pen-nib"></i> Plot',
            'y-start': `<i class="fas fa-arrows-alt-v"></i> Y1:${state.settings.yStart}%`,
            'y-end': `<i class="fas fa-arrows-alt-v"></i> Y2:${state.settings.yEnd}%`,
            'fullscreen': state.isFullscreen ? '<i class="fas fa-compress"></i>' : '<i class="fas fa-expand"></i>',
            'audio-toggle': `<i class="fas fa-microphone${state.audioEnabled ? '' : '-slash'}"></i> ${state.audioEnabled ? 'ON' : 'OFF'}`,
            'audio-voice': `<i class="fas fa-robot"></i> ${state.audioVoice.charAt(0).toUpperCase() + state.audioVoice.slice(1)}`,
            'crop-left': `<i class="fas fa-chevron-left"></i> L:${state.crop.left}%`,
            'crop-right': `<i class="fas fa-chevron-right"></i> R:${state.crop.right}%`,
            'crop-top': `<i class="fas fa-chevron-up"></i> T:${state.crop.top}%`,
            'crop-bottom': `<i class="fas fa-chevron-down"></i> B:${state.crop.bottom}%`,
            'reset-crop': '<i class="fas fa-undo"></i> Reset'
        };
        return labels[control] || control;
    }

    // Audio streaming functions
    async function startAudioStream() {
        if (state.audioRecording) return;
        
        try {
            // Get microphone access - let browser use default sample rate
            state.audioStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl: false
                }
            });
            
            // Create audio context - use default sample rate to match microphone
            state.audioContext = new AudioContext();
            
            const source = state.audioContext.createMediaStreamSource(state.audioStream);
            const actualSampleRate = state.audioContext.sampleRate;
            
            // Create processor node for raw PCM output
            // Use buffer size based on actual sample rate for ~100ms chunks
            const bufferSize = Math.pow(2, Math.ceil(Math.log2(actualSampleRate * 0.1)));
            const processor = state.audioContext.createScriptProcessor(bufferSize, 1, 1);
            
            processor.onaudioprocess = function(e) {
                if (!state.audioRecording) return;
                
                const inputData = e.inputBuffer.getChannelData(0);
                
                // Convert Float32 to Int16
                const int16Data = new Int16Array(inputData.length);
                for (let i = 0; i < inputData.length; i++) {
                    const s = Math.max(-1, Math.min(1, inputData[i]));
                    int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                
                // Convert to base64 and send with sample rate
                const base64Audio = arrayBufferToBase64(int16Data.buffer);
                
                if (state.audioSocket && state.audioSocket.connected) {
                    state.audioSocket.emit('audio_chunk', { 
                        audio: base64Audio,
                        sample_rate: actualSampleRate 
                    });
                }
            };
            
            source.connect(processor);
            processor.connect(state.audioContext.destination);
            state.audioWorklet = processor;
            
            // Connect to SocketIO
            await connectAudioSocket();
            
            state.audioRecording = true;
            updateStatus('Audio streaming started');
            
        } catch (e) {
            console.error('Failed to start audio:', e);
            updateStatus('Audio failed: ' + e.message);
            state.audioEnabled = false;
            saveSettings();
            updateUI();
        }
    }
    
    function stopAudioStream() {
        state.audioRecording = false;
        
        // Stop audio processing
        if (state.audioWorklet) {
            state.audioWorklet.disconnect();
            state.audioWorklet = null;
        }
        
        // Stop microphone
        if (state.audioStream) {
            state.audioStream.getTracks().forEach(track => track.stop());
            state.audioStream = null;
        }
        
        // Close audio context
        if (state.audioContext) {
            state.audioContext.close();
            state.audioContext = null;
        }
        
        // Stop streaming on backend
        if (state.audioSocket && state.audioSocket.connected) {
            state.audioSocket.emit('stop_stream', {});
        }
        
        updateStatus('Audio stopped');
    }
    
    function changeAudioVoice(voice) {
        if (state.audioSocket && state.audioSocket.connected) {
            state.audioSocket.emit('change_preset', { preset: voice });
        }
    }
    
    function connectAudioSocket() {
        return new Promise((resolve, reject) => {
            if (state.audioSocket && state.audioSocket.connected) {
                resolve();
                return;
            }
            
            // Load SocketIO client if not already loaded
            if (typeof io === 'undefined') {
                const script = document.createElement('script');
                script.src = '/socket.io/socket.io.js';
                script.onload = () => initAudioSocket(resolve, reject);
                script.onerror = reject;
                document.head.appendChild(script);
            } else {
                initAudioSocket(resolve, reject);
            }
        });
    }
    
    function initAudioSocket(resolve, reject) {
        state.audioSocket = io('/audio', { transports: ['websocket', 'polling'] });
        
        state.audioSocket.on('connect', () => {
            console.log('Audio socket connected');
            state.audioSocket.emit('start_stream', { preset: state.audioVoice });
            resolve();
        });
        
        state.audioSocket.on('connect_error', (e) => {
            console.error('Audio socket error:', e);
            reject(e);
        });
        
        state.audioSocket.on('stream_started', (data) => {
            console.log('Audio stream started:', data);
        });
        
        state.audioSocket.on('stream_stopped', (data) => {
            console.log('Audio stream stopped:', data);
        });
    }
    
    function arrayBufferToBase64(buffer) {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return btoa(binary);
    }
    
    // Auto-start audio if enabled
    function maybeStartAudio() {
        if (state.audioEnabled && !state.audioRecording) {
            startAudioStream();
        }
    }
})();
