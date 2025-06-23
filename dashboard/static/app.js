let ws = null;
let currentConfig = null;

// WebSocket connection
function connectWebSocket() {
    ws = new WebSocket('ws://localhost:8000/ws');
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        updateConnectionStatus(true);
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);
        setTimeout(connectWebSocket, 5000);
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };
    
    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };
}

function updateConnectionStatus(connected) {
    const statusDot = document.getElementById('connection-status');
    const statusText = document.getElementById('connection-text');
    
    if (connected) {
        statusDot.classList.add('connected');
        statusText.textContent = 'Connected';
    } else {
        statusDot.classList.remove('connected');
        statusText.textContent = 'Disconnected';
    }
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'config_updated':
            showNotification('Config updated successfully', 'success');
            break;
        case 'backtest_started':
            showNotification('Backtest started...', 'info');
            break;
        case 'backtest_completed':
            displayBacktestResults(data.results);
            showNotification('Backtest completed', 'success');
            break;
        case 'backtest_error':
            showNotification(`Backtest error: ${data.error}`, 'error');
            break;
    }
}

// Navigation
document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const page = e.target.getAttribute('data-page');
        showPage(page);
        
        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        e.target.classList.add('active');
    });
});

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(page => {
        page.classList.remove('active');
    });
    document.getElementById(`${pageId}-page`).classList.add('active');
    
    if (pageId === 'monitor') {
        loadMonitorData();
    }
}

// Config Editor
document.getElementById('load-config').addEventListener('click', async () => {
    const configType = document.getElementById('config-type').value;
    try {
        const response = await fetch(`/api/config/${configType}`);
        const data = await response.json();
        currentConfig = data.config;
        document.getElementById('config-content').value = jsyaml.dump(data.config);
    } catch (error) {
        showNotification('Failed to load config', 'error');
    }
});

document.getElementById('save-config').addEventListener('click', async () => {
    const configType = document.getElementById('config-type').value;
    const configContent = document.getElementById('config-content').value;
    
    try {
        const configData = jsyaml.load(configContent);
        const response = await fetch('/api/config/update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                config_type: configType,
                config_data: configData
            })
        });
        
        if (response.ok) {
            showNotification('Config saved successfully', 'success');
        } else {
            showNotification('Failed to save config', 'error');
        }
    } catch (error) {
        showNotification('Invalid YAML format', 'error');
    }
});

document.getElementById('reset-config').addEventListener('click', () => {
    if (currentConfig) {
        document.getElementById('config-content').value = jsyaml.dump(currentConfig);
    }
});

// Backtest
document.getElementById('run-backtest').addEventListener('click', async () => {
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value;
    const initialBalance = parseFloat(document.getElementById('initial-balance').value);
    const configType = document.getElementById('backtest-config').value;
    
    if (!startDate || !endDate) {
        showNotification('Please select start and end dates', 'error');
        return;
    }
    
    try {
        const response = await fetch('/api/backtest', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                start_date: startDate,
                end_date: endDate,
                initial_balance: initialBalance,
                config_type: configType
            })
        });
        
        if (!response.ok) {
            throw new Error('Backtest failed');
        }
    } catch (error) {
        showNotification('Failed to start backtest', 'error');
    }
});

function displayBacktestResults(results) {
    document.getElementById('backtest-results').style.display = 'block';
    document.getElementById('total-return').textContent = `${results.total_return}%`;
    document.getElementById('sharpe-ratio').textContent = results.sharpe_ratio;
    document.getElementById('max-drawdown').textContent = `${results.max_drawdown}%`;
    document.getElementById('total-trades').textContent = results.total_trades;
    
    // Mock equity curve
    const trace = {
        x: Array.from({length: 100}, (_, i) => i),
        y: Array.from({length: 100}, (_, i) => 10000 * (1 + 0.001 * i + 0.01 * Math.sin(i/10))),
        type: 'scatter',
        name: 'Equity Curve'
    };
    
    const layout = {
        title: 'Equity Curve',
        xaxis: { title: 'Days' },
        yaxis: { title: 'Balance ($)' },
        paper_bgcolor: '#1a1a1a',
        plot_bgcolor: '#1a1a1a',
        font: { color: '#e0e0e0' }
    };
    
    Plotly.newPlot('equity-curve', [trace], layout);
}

// Monitor
async function loadMonitorData() {
    try {
        const [exchangesRes, pairsRes] = await Promise.all([
            fetch('/api/exchanges'),
            fetch('/api/trading-pairs')
        ]);
        
        const exchanges = await exchangesRes.json();
        const pairs = await pairsRes.json();
        
        const exchangesList = document.getElementById('active-exchanges');
        exchangesList.innerHTML = exchanges.exchanges.map(ex => `<li>${ex}</li>`).join('');
        
        const pairsList = document.getElementById('trading-pairs');
        pairsList.innerHTML = pairs.pairs.map(pair => `<li>${pair}</li>`).join('');
        
    } catch (error) {
        console.error('Failed to load monitor data:', error);
    }
}

// Notifications
function showNotification(message, type) {
    console.log(`[${type}] ${message}`);
    // TODO: Implement visual notifications
}

// Initialize
connectWebSocket();

// Load js-yaml library
const script = document.createElement('script');
script.src = 'https://cdn.jsdelivr.net/npm/js-yaml@4.1.0/dist/js-yaml.min.js';
document.head.appendChild(script);

// Load initial config on page load
window.addEventListener('load', () => {
    document.getElementById('load-config').click();
});