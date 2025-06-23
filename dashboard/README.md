# Arbitrage Bot Dashboard

A web-based dashboard for managing and monitoring the arbitrage bot.

## Features

- **Config Editor**: Edit bot_config.yaml and production_config.yaml with syntax highlighting
- **Backtest Engine**: Run backtests with custom date ranges and parameters
- **Real-time Monitor**: View active exchanges, trading pairs, and opportunities
- **WebSocket Support**: Real-time updates for config changes and backtest results

## Installation

```bash
cd dashboard
pip install -r requirements.txt
```

## Running the Dashboard

```bash
python run.py
```

Or directly:
```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8001
```

Access the dashboard at: http://localhost:8001

## How to Use

### Left Navigation

The dashboard has **3 main sections**:

#### 1. Config Editor (設定エディタ)
- **Config Type**: Select `Development` or `Production`
- **Load Config**: Load the selected configuration file
- **YAML Edit Area**: Edit settings directly in YAML format
- **Save Config**: Save your changes
- **Reset**: Revert to original settings

#### 2. Backtest (バックテスト)
- **Start Date/End Date**: Specify backtest period
- **Initial Balance**: Set starting balance
- **Config**: Choose configuration to use
- **Run Backtest**: Execute backtest
- **Results Display**: View returns, Sharpe ratio, max drawdown and equity curve chart

#### 3. Monitor (監視)
- **Active Exchanges**: List of configured exchanges
- **Trading Pairs**: List of trading pairs
- **Recent Opportunities**: Latest arbitrage opportunities

### Basic Workflow

1. **Check Settings**: First, review current settings in "Config Editor"
2. **Edit Configuration**: Modify exchange API keys and trading pairs as needed
3. **Run Backtest**: Use "Backtest" to test performance on historical data
4. **Monitor**: Use "Monitor" to view real-time status

The green dot (●) in the top right shows connection status. Real-time updates via WebSocket.

## API Endpoints

- `GET /`: Main dashboard interface
- `GET /api/config/{config_type}`: Get configuration (bot/production)
- `POST /api/config/update`: Update configuration
- `POST /api/backtest`: Run backtest
- `GET /api/exchanges`: Get list of configured exchanges
- `GET /api/trading-pairs`: Get list of trading pairs
- `WS /ws`: WebSocket connection for real-time updates

## Architecture

- **Backend**: FastAPI with WebSocket support
- **Frontend**: Vanilla JavaScript with real-time updates
- **Styling**: Dark theme optimized for trading environments
- **Charts**: Plotly.js for data visualization