// Check if Capacitor is available (native app) or use web fallback
const isNativeApp = window.Capacitor !== undefined;
const Camera = isNativeApp ? window.Capacitor.Plugins.Camera : null;

// App state
let config = {
    aiProvider: 'openai',
    apiKey: '',
    taskDescription: '',
    facingMode: 'back'
};

let currentPhotoBase64 = null;
let isListening = false;
let recognition = null;
let conversationHistory = [];

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    loadSavedSettings();
    initializeSpeechRecognition();
    initializeAudioRouting();
});

// Load saved settings
function loadSavedSettings() {
    const savedProvider = localStorage.getItem('aiProvider');
    const savedKey = localStorage.getItem('apiKey');

    if (savedProvider) {
        document.getElementById('aiProvider').value = savedProvider;
    }
    if (savedKey) {
        document.getElementById('apiKey').value = savedKey;
    }
}

// Start the app
async function startApp() {
    const apiKey = document.getElementById('apiKey').value.trim();
    const taskDescription = document.getElementById('taskDescription').value.trim();
    const aiProvider = document.getElementById('aiProvider').value;

    if (!apiKey) {
        alert('Please enter your API key');
        return;
    }

    if (!taskDescription) {
        alert('Please describe what you need help with');
        return;
    }

    config.apiKey = apiKey;
    config.taskDescription = taskDescription;
    config.aiProvider = aiProvider;

    // Save settings
    localStorage.setItem('aiProvider', aiProvider);
    localStorage.setItem('apiKey', apiKey);

    // Switch to camera view
    document.getElementById('setupView').classList.add('hidden');
    document.getElementById('cameraView').classList.add('active');

    // Initialize camera
    await initializeCamera();
}

// Initialize camera (native or web)
async function initializeCamera() {
    if (isNativeApp) {
        // Native app - camera is ready, just show the view
        document.getElementById('statusText').textContent = 'Tap button to capture';
    } else {
        // Web fallback - use MediaDevices API
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: config.facingMode === 'back' ? 'environment' : 'user',
                    width: { ideal: 1920 },
                    height: { ideal: 1080 }
                }
            });

            const videoElement = document.createElement('video');
            videoElement.srcObject = stream;
            videoElement.autoplay = true;
            videoElement.playsInline = true;
            videoElement.className = 'camera-preview';

            const preview = document.getElementById('cameraPreview');
            preview.replaceWith(videoElement);

            window.videoStream = stream;
            window.videoElement = videoElement;
        } catch (err) {
            showError('Camera access denied. Please enable camera permissions.');
        }
    }
}

// Flip camera
async function flipCamera() {
    config.facingMode = config.facingMode === 'back' ? 'front' : 'back';
    await initializeCamera();
}

// Capture photo
async function capturePhoto() {
    try {
        if (isNativeApp) {
            // Use native Capacitor Camera
            const photo = await Camera.getPhoto({
                quality: 80,
                allowEditing: false,
                resultType: 'base64',
                source: 'camera',
                direction: config.facingMode === 'back' ? 'rear' : 'front'
            });

            currentPhotoBase64 = photo.base64String;
            showPhotoPreview(`data:image/jpeg;base64,${photo.base64String}`);
            analyzePhoto(photo.base64String);

        } else {
            // Web fallback - capture from video
            const video = window.videoElement;
            if (!video) {
                showError('Camera not initialized');
                return;
            }

            const canvas = document.createElement('canvas');
            canvas.width = 1080;
            canvas.height = Math.round(1080 * (video.videoHeight / video.videoWidth));

            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

            const base64Full = canvas.toDataURL('image/jpeg', 0.8);
            const base64 = base64Full.split(',')[1];

            currentPhotoBase64 = base64;
            showPhotoPreview(base64Full);
            analyzePhoto(base64);
        }
    } catch (err) {
        showError('Failed to capture photo: ' + err.message);
    }
}

// Show photo preview
function showPhotoPreview(dataUrl) {
    const preview = document.getElementById('photoPreview');
    preview.src = dataUrl;
    preview.classList.add('active');
    document.getElementById('cameraControls').classList.add('hidden');
}

// Analyze photo with AI
async function analyzePhoto(base64Image) {
    document.getElementById('loadingOverlay').classList.add('active');
    document.getElementById('statusText').textContent = 'Analyzing image...';

    try {
        let result;
        if (config.aiProvider === 'openai') {
            result = await analyzeWithOpenAI(base64Image);
        } else {
            result = await analyzeWithClaude(base64Image);
        }

        displayResult(result);
    } catch (err) {
        showError('Analysis failed: ' + err.message);
    } finally {
        document.getElementById('loadingOverlay').classList.remove('active');
    }
}

// Analyze with OpenAI GPT-4 Vision
async function analyzeWithOpenAI(base64Image) {
    const prompt = `You are an expert technical assistant helping someone with: "${config.taskDescription}"

Analyze this image and provide helpful, actionable instructions. Be specific and practical.

Respond in this exact JSON format:
{
  "status": "correct" | "needs_adjustment" | "problem_found" | "unclear",
  "instruction": "Clear, actionable instruction (max 30 words)",
  "reasoning": "Brief technical explanation of what you see",
  "next_steps": "What they should do next"
}`;

    const response = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${config.apiKey}`
        },
        body: JSON.stringify({
            model: 'gpt-4o',
            messages: [
                {
                    role: 'user',
                    content: [
                        { type: 'text', text: prompt },
                        {
                            type: 'image_url',
                            image_url: {
                                url: `data:image/jpeg;base64,${base64Image}`,
                                detail: 'high'
                            }
                        }
                    ]
                }
            ],
            max_tokens: 500,
            temperature: 0.3
        })
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error?.message || 'API request failed');
    }

    const data = await response.json();
    let content = data.choices[0].message.content;
    content = content.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();

    try {
        return JSON.parse(content);
    } catch {
        return {
            status: 'unclear',
            instruction: content.substring(0, 200),
            reasoning: 'AI provided text response',
            next_steps: 'Take another photo if needed'
        };
    }
}

// Analyze with Anthropic Claude
async function analyzeWithClaude(base64Image) {
    const prompt = `You are an expert technical assistant helping someone with: "${config.taskDescription}"

Analyze this image and provide helpful, actionable instructions. Be specific and practical.

Respond in this exact JSON format:
{
  "status": "correct" | "needs_adjustment" | "problem_found" | "unclear",
  "instruction": "Clear, actionable instruction (max 30 words)",
  "reasoning": "Brief technical explanation of what you see",
  "next_steps": "What they should do next"
}`;

    const response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-api-key': config.apiKey,
            'anthropic-version': '2023-06-01'
        },
        body: JSON.stringify({
            model: 'claude-sonnet-4-20250514',
            max_tokens: 1024,
            messages: [
                {
                    role: 'user',
                    content: [
                        {
                            type: 'image',
                            source: {
                                type: 'base64',
                                media_type: 'image/jpeg',
                                data: base64Image
                            }
                        },
                        {
                            type: 'text',
                            text: prompt
                        }
                    ]
                }
            ]
        })
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error?.message || 'API request failed');
    }

    const data = await response.json();
    let content = data.content[0].text;
    content = content.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();

    try {
        return JSON.parse(content);
    } catch {
        return {
            status: 'unclear',
            instruction: content.substring(0, 200),
            reasoning: 'AI provided text response',
            next_steps: 'Take another photo if needed'
        };
    }
}

// Display analysis result
function displayResult(result) {
    const statusMap = {
        'correct': 'Looks Good',
        'needs_adjustment': 'Needs Adjustment',
        'problem_found': 'Problem Found',
        'unclear': 'Unclear'
    };

    const panel = document.getElementById('resultPanel');
    panel.innerHTML = `
        <div class="result-status status-${result.status}">
            ${statusMap[result.status] || 'Analysis Complete'}
        </div>
        <div class="result-instruction">${result.instruction}</div>
        ${result.next_steps ? `<div class="result-next-steps">→ ${result.next_steps}</div>` : ''}
        <div class="result-reasoning">${result.reasoning}</div>
        <div class="action-buttons">
            <button class="btn-secondary" onclick="retakePhoto()">Retake</button>
            <button class="btn-primary" onclick="takeAnother()">Next Photo</button>
        </div>
        <div class="voice-controls">
            <button id="micBtn" class="btn-voice ${isListening ? 'listening' : ''}" onclick="toggleVoiceInput()">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                </svg>
                <span>${isListening ? 'Listening...' : 'Ask a Question'}</span>
            </button>
        </div>
        <button class="btn-secondary" style="margin-top: 12px;" onclick="changeSettings()">Change Settings</button>
    `;
    panel.classList.add('active');
    document.getElementById('statusText').textContent = statusMap[result.status] || 'Complete';

    // Save to conversation history
    conversationHistory.push({
        role: 'assistant',
        content: result.instruction,
        imageContext: true
    });

    // Speak instruction with audio routing
    speakText(result.instruction);
}

// Show error
function showError(message) {
    const panel = document.getElementById('resultPanel');
    panel.innerHTML = `
        <div class="error-message">
            <strong>Error:</strong> ${message}
        </div>
        <button class="btn-primary" onclick="retakePhoto()">Try Again</button>
        <button class="btn-secondary" style="margin-top: 12px;" onclick="changeSettings()">Change Settings</button>
    `;
    panel.classList.add('active');
}

// Retake photo
function retakePhoto() {
    document.getElementById('photoPreview').classList.remove('active');
    document.getElementById('resultPanel').classList.remove('active');
    document.getElementById('cameraControls').classList.remove('hidden');
    document.getElementById('statusText').textContent = 'Point camera at the problem';
}

// Take another photo
function takeAnother() {
    retakePhoto();
}

// Change settings
function changeSettings() {
    // Stop camera if web
    if (window.videoStream) {
        window.videoStream.getTracks().forEach(track => track.stop());
    }

    // Stop voice recognition
    if (recognition) {
        recognition.stop();
        isListening = false;
    }

    document.getElementById('cameraView').classList.remove('active');
    document.getElementById('setupView').classList.remove('hidden');
    document.getElementById('photoPreview').classList.remove('active');
    document.getElementById('resultPanel').classList.remove('active');
    document.getElementById('cameraControls').classList.remove('hidden');
}

// ========== BLUETOOTH AUDIO & VOICE INTERACTION ==========

// Initialize audio routing for Bluetooth devices
function initializeAudioRouting() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
        console.log('Audio device enumeration not supported');
        return;
    }

    // Monitor audio device changes (AirPods connect/disconnect)
    navigator.mediaDevices.addEventListener('devicechange', handleAudioDeviceChange);

    // Initial check
    checkAudioDevices();
}

// Check for connected audio devices
async function checkAudioDevices() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioOutputs = devices.filter(device => device.kind === 'audiooutput');
        const audioInputs = devices.filter(device => device.kind === 'audioinput');

        // Look for Bluetooth devices (AirPods, headphones, etc.)
        const bluetoothOutput = audioOutputs.find(device =>
            device.label.toLowerCase().includes('airpod') ||
            device.label.toLowerCase().includes('bluetooth') ||
            device.label.toLowerCase().includes('headphone') ||
            device.label.toLowerCase().includes('earbuds')
        );

        const bluetoothInput = audioInputs.find(device =>
            device.label.toLowerCase().includes('airpod') ||
            device.label.toLowerCase().includes('bluetooth') ||
            device.label.toLowerCase().includes('headphone') ||
            device.label.toLowerCase().includes('earbuds')
        );

        if (bluetoothOutput || bluetoothInput) {
            console.log('Bluetooth audio device detected:', bluetoothOutput?.label || bluetoothInput?.label);
            updateAudioStatus(true, bluetoothOutput?.label || bluetoothInput?.label);
        } else {
            updateAudioStatus(false);
        }
    } catch (err) {
        console.error('Error checking audio devices:', err);
    }
}

// Handle audio device changes
function handleAudioDeviceChange() {
    console.log('Audio device changed');
    checkAudioDevices();
}

// Update UI to show audio device status
function updateAudioStatus(isBluetoothConnected, deviceName = '') {
    const statusText = document.getElementById('statusText');
    if (!statusText) return;

    if (isBluetoothConnected) {
        const deviceShortName = deviceName.substring(0, 20);
        console.log(`Bluetooth connected: ${deviceShortName}`);
    }
}

// Enhanced text-to-speech with audio routing
function speakText(text, options = {}) {
    if (!('speechSynthesis' in window)) {
        console.log('Speech synthesis not supported');
        return;
    }

    // Cancel any ongoing speech
    speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = options.rate || 0.9;
    utterance.pitch = options.pitch || 1.0;
    utterance.volume = options.volume || 1.0;

    // Get available voices and prefer higher quality ones
    const voices = speechSynthesis.getVoices();
    if (voices.length > 0) {
        // Prefer English voices, specifically Google or Apple voices for quality
        const preferredVoice = voices.find(voice =>
            voice.lang.startsWith('en') &&
            (voice.name.includes('Google') || voice.name.includes('Apple'))
        ) || voices.find(voice => voice.lang.startsWith('en'));

        if (preferredVoice) {
            utterance.voice = preferredVoice;
        }
    }

    utterance.onstart = () => {
        console.log('Speaking:', text.substring(0, 50));
    };

    utterance.onerror = (event) => {
        console.error('Speech synthesis error:', event.error);
    };

    // Audio will automatically route to connected Bluetooth device
    speechSynthesis.speak(utterance);
}

// Initialize speech recognition
function initializeSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        console.log('Speech recognition not supported in this browser');
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
        console.log('Voice recognition started');
        isListening = true;
        updateMicButton();
    };

    recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        console.log('User said:', transcript);
        handleVoiceQuestion(transcript);
    };

    recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        isListening = false;
        updateMicButton();

        if (event.error === 'no-speech') {
            speakText('I didn\'t hear anything. Please try again.');
        } else if (event.error === 'not-allowed') {
            alert('Microphone permission denied. Please enable microphone access in your device settings.');
        }
    };

    recognition.onend = () => {
        console.log('Voice recognition ended');
        isListening = false;
        updateMicButton();
    };
}

// Toggle voice input
function toggleVoiceInput() {
    if (!recognition) {
        alert('Voice recognition is not available on this device.');
        return;
    }

    if (isListening) {
        recognition.stop();
        isListening = false;
    } else {
        recognition.start();
        isListening = true;
        speakText('I\'m listening. What would you like to know?');
    }

    updateMicButton();
}

// Update microphone button appearance
function updateMicButton() {
    const micBtn = document.getElementById('micBtn');
    if (!micBtn) return;

    if (isListening) {
        micBtn.classList.add('listening');
        micBtn.innerHTML = `
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
            <span>Listening...</span>
        `;
    } else {
        micBtn.classList.remove('listening');
        micBtn.innerHTML = `
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
            </svg>
            <span>Ask a Question</span>
        `;
    }
}

// Handle voice questions from user
async function handleVoiceQuestion(question) {
    conversationHistory.push({
        role: 'user',
        content: question
    });

    const statusText = document.getElementById('statusText');
    if (statusText) {
        statusText.textContent = 'Thinking...';
    }

    speakText('Let me think about that.');

    try {
        let answer;
        if (config.aiProvider === 'openai') {
            answer = await askQuestionOpenAI(question);
        } else {
            answer = await askQuestionClaude(question);
        }

        conversationHistory.push({
            role: 'assistant',
            content: answer
        });

        displayVoiceAnswer(question, answer);
        speakText(answer);

    } catch (err) {
        console.error('Error processing voice question:', err);
        const errorMsg = 'Sorry, I had trouble processing your question. Please try again.';
        speakText(errorMsg);
        showError(errorMsg);
    }
}

// Ask follow-up question to OpenAI
async function askQuestionOpenAI(question) {
    const messages = [
        {
            role: 'system',
            content: `You are a helpful technical assistant. The user is working on: "${config.taskDescription}". Provide clear, concise answers in 2-3 sentences.`
        }
    ];

    // Add conversation history
    conversationHistory.slice(-6).forEach(msg => {
        if (msg.imageContext) {
            messages.push({
                role: msg.role,
                content: `[Previously analyzed image] ${msg.content}`
            });
        } else {
            messages.push({
                role: msg.role,
                content: msg.content
            });
        }
    });

    const response = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${config.apiKey}`
        },
        body: JSON.stringify({
            model: 'gpt-4o',
            messages: messages,
            max_tokens: 200,
            temperature: 0.7
        })
    });

    if (!response.ok) {
        throw new Error('Failed to get response from OpenAI');
    }

    const data = await response.json();
    return data.choices[0].message.content;
}

// Ask follow-up question to Claude
async function askQuestionClaude(question) {
    const messages = [];

    conversationHistory.slice(-6).forEach(msg => {
        if (msg.imageContext) {
            messages.push({
                role: msg.role,
                content: `[Previously analyzed image] ${msg.content}`
            });
        } else {
            messages.push({
                role: msg.role,
                content: msg.content
            });
        }
    });

    const response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'x-api-key': config.apiKey,
            'anthropic-version': '2023-06-01'
        },
        body: JSON.stringify({
            model: 'claude-sonnet-4-20250514',
            max_tokens: 300,
            system: `You are a helpful technical assistant. The user is working on: "${config.taskDescription}". Provide clear, concise answers in 2-3 sentences.`,
            messages: messages
        })
    });

    if (!response.ok) {
        throw new Error('Failed to get response from Claude');
    }

    const data = await response.json();
    return data.content[0].text;
}

// Display voice Q&A in result panel
function displayVoiceAnswer(question, answer) {
    const panel = document.getElementById('resultPanel');

    const qaHTML = `
        <div class="voice-qa">
            <div class="voice-question">
                <strong>You asked:</strong> ${question}
            </div>
            <div class="voice-answer">
                <strong>Answer:</strong> ${answer}
            </div>
        </div>
    `;

    // Insert before the voice controls
    const voiceControls = panel.querySelector('.voice-controls');
    if (voiceControls) {
        voiceControls.insertAdjacentHTML('beforebegin', qaHTML);
    }

    // Auto-scroll to bottom
    panel.scrollTop = panel.scrollHeight;
}
