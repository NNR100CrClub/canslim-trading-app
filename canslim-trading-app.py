import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import nsepy
from datetime import datetime, timedelta
import plotly.graph_objects as go
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import time
import base64
from io import StringIO
from PIL import Image
import requests
import json
from dateutil.relativedelta import relativedelta
from io import BytesIO
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.lines import Line2D

# Set page configuration
st.set_page_config(
    page_title="CAN SLIM Trader",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ----- Helper Functions -----

def calculate_rs(stock_df, index_df, period=90):
    """Calculate Relative Strength of a stock against an index"""
    if len(stock_df) < period or len(index_df) < period:
        return 0
    
    stock_returns = (stock_df['Close'].iloc[-1] / stock_df['Close'].iloc[-period]) - 1
    index_returns = (index_df['Close'].iloc[-1] / index_df['Close'].iloc[-period]) - 1
    
    if index_returns == 0:
        return 50  # Neutral if index hasn't moved
    
    rs = ((1 + stock_returns) / (1 + index_returns)) * 50
    
    # Scale to 0-100 range
    rs = min(max(rs, 0), 100)
    
    return round(rs, 1)

def get_stock_data(symbol, period="1y"):
    """Get stock data using nsepy or yfinance as fallback"""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        if symbol.endswith('.NS') or symbol.endswith('.BO'):
            clean_symbol = symbol.split('.')[0]
        else:
            clean_symbol = symbol
        
        # Try nsepy first
        try:
            data = nsepy.get_history(symbol=clean_symbol, 
                                     start=start_date, 
                                     end=end_date)
            if len(data) < 20:  # Not enough data
                raise Exception("Insufficient data from NSEPy")
            
            # Rename columns to match yfinance format
            data = data.rename(columns={
                'Close': 'Close',
                'High': 'High',
                'Low': 'Low',
                'Open': 'Open',
                'Volume': 'Volume'
            })
            
            return data
            
        except Exception as e:
            # Fallback to yfinance
            ticker = f"{clean_symbol}.NS" if not symbol.endswith('.NS') and not symbol.endswith('.BO') else symbol
            data = yf.download(ticker, period=period)
            return data
            
    except Exception as e:
        st.error(f"Error fetching data for {symbol}: {e}")
        return pd.DataFrame()

def get_nifty_data(period="1y"):
    """Get Nifty 50 index data"""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        # Try nsepy first
        try:
            data = nsepy.get_history(symbol="NIFTY 50", 
                                     start=start_date, 
                                     end=end_date,
                                     index=True)
            if len(data) < 20:  # Not enough data
                raise Exception("Insufficient data from NSEPy")
            
            # Rename columns to match yfinance format
            data = data.rename(columns={
                'Close': 'Close',
                'High': 'High',
                'Low': 'Low',
                'Open': 'Open'
            })
            
            return data
            
        except Exception as e:
            # Fallback to yfinance
            data = yf.download("^NSEI", period=period)
            return data
            
    except Exception as e:
        st.error(f"Error fetching Nifty data: {e}")
        return pd.DataFrame()

def calculate_ma(df, period=200):
    """Calculate moving average"""
    if len(df) < period:
        return df.assign(MA=np.nan)
    
    df = df.copy()
    df[f'MA_{period}'] = df['Close'].rolling(window=period).mean()
    return df

def identify_cup_with_handle(df, lookback_period=90):
    """Identify cup with handle pattern"""
    if len(df) < lookback_period:
        return False, {}
    
    # Get relevant data
    data = df.iloc[-lookback_period:].copy()
    
    # Find the highest high and lowest low in the period
    high = data['High'].max()
    high_idx = data['High'].idxmax()
    
    # Look for a dip of at least 15% from high
    min_after_high = data.loc[data.index > high_idx, 'Low'].min()
    if min_after_high > high * 0.85:  # Need at least 15% dip
        return False, {}
    
    # Look for recovery to at least 90% of previous high
    current = data['Close'].iloc[-1]
    if current < high * 0.9:
        return False, {}
    
    # Check if there's a handle - a smaller dip of 5-10% after recovery
    recovery_idx = None
    for i in range(len(data)-1, 0, -1):
        if data['Close'].iloc[i] >= high * 0.9:
            recovery_idx = data.index[i]
            break
    
    if recovery_idx is None:
        return False, {}
    
    # Find handle low
    handle_data = data.loc[data.index >= recovery_idx]
    if len(handle_data) < 5:  # Need at least 5 days for a handle
        return False, {}
    
    handle_low = handle_data['Low'].min()
    
    # Handle should have smaller dip than cup
    if handle_low < min_after_high:
        return False, {}
    
    # Handle should be shorter than cup
    cup_days = (recovery_idx - high_idx).days
    handle_days = (data.index[-1] - recovery_idx).days
    
    if handle_days > cup_days:
        return False, {}
    
    pattern_data = {
        'cup_high': high,
        'cup_low': min_after_high,
        'handle_low': handle_low,
        'current': current
    }
    
    return True, pattern_data

def check_earnings_growth(fundamentals_df, symbol, min_growth=15):
    """Check if a stock meets the earnings growth criteria"""
    if fundamentals_df is None or fundamentals_df.empty:
        return False, 0
    
    if symbol not in fundamentals_df['Symbol'].values:
        return False, 0
    
    stock_data = fundamentals_df[fundamentals_df['Symbol'] == symbol]
    
    # Check if we have EPS growth data
    if 'EPS_Growth_1Y' not in stock_data.columns:
        return False, 0
    
    eps_growth = stock_data['EPS_Growth_1Y'].values[0]
    
    try:
        eps_growth = float(eps_growth.strip('%')) if isinstance(eps_growth, str) else float(eps_growth)
    except:
        return False, 0
    
    return eps_growth >= min_growth, eps_growth

def set_target_sl(df, cup_handle_data=None, risk_percent=7, reward_ratio=3):
    """Set target and stop loss based on CAN SLIM criteria"""
    if df.empty:
        return None, None, None
    
    current_price = df['Close'].iloc[-1]
    
    if cup_handle_data:
        # If we have cup with handle pattern, use the handle low for SL
        stop_loss = cup_handle_data['handle_low'] * 0.97  # 3% below handle low
    else:
        # Otherwise use a percentage-based SL
        stop_loss = current_price * (1 - risk_percent/100)
    
    risk = current_price - stop_loss
    target = current_price + (risk * reward_ratio)
    
    return current_price, round(target, 2), round(stop_loss, 2)

def send_email_alert(recipient, subject, body):
    """Send email alerts using SMTP"""
    sender_email = st.session_state.get('email_sender', '')
    sender_password = st.session_state.get('email_password', '')
    
    if not sender_email or not sender_password:
        st.warning("Email credentials not set. Please configure in settings.")
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Determine the email provider
        if '@gmail.com' in sender_email:
            smtp_server = "smtp.gmail.com"
            port = 587
        elif '@yahoo.com' in sender_email:
            smtp_server = "smtp.mail.yahoo.com"
            port = 587
        elif '@outlook.com' in sender_email or '@hotmail.com' in sender_email:
            smtp_server = "smtp-mail.outlook.com"
            port = 587
        else:
            st.error("Unsupported email provider. Please use Gmail, Yahoo, or Outlook.")
            return False
        
        server = smtplib.SMTP(smtp_server, port)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, recipient, text)
        server.quit()
        
        return True
    
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

def get_sector_strength():
    """Analyze sector strength based on price vs MA and RS"""
    sectors = [
        "NIFTY AUTO", "NIFTY BANK", "NIFTY PHARMA", "NIFTY IT", 
        "NIFTY FMCG", "NIFTY METAL", "NIFTY REALTY"
    ]
    
    sector_strength = []
    nifty_index = get_nifty_data("3mo")
    
    for sector in sectors:
        try:
            sector_data = nsepy.get_history(symbol=sector, 
                                          start=datetime.now() - timedelta(days=200), 
                                          end=datetime.now(),
                                          index=True)
            
            if len(sector_data) < 100:
                continue
                
            # Calculate 200-day MA
            sector_data = calculate_ma(sector_data, period=200)
            
            # Check if price > 200MA
            price_above_ma = sector_data['Close'].iloc[-1] > sector_data['MA_200'].iloc[-1]
            
            # Calculate Relative Strength vs Nifty
            rs = calculate_rs(sector_data.iloc[-90:], nifty_index.iloc[-90:])
            
            sector_strength.append({
                'sector': sector,
                'price_above_ma': price_above_ma,
                'rs': rs,
                'score': (rs if price_above_ma else rs * 0.5)  # Higher score if above MA
            })
            
        except Exception as e:
            st.error(f"Error analyzing sector {sector}: {e}")
    
    # Sort by score
    sector_strength.sort(key=lambda x: x['score'], reverse=True)
    return sector_strength

def validate_stock(symbol, fundamentals_df=None):
    """Validate if a stock meets CAN SLIM criteria"""
    stock_df = get_stock_data(symbol)
    
    if stock_df.empty:
        return {
            'valid': False,
            'message': f"Could not fetch data for {symbol}"
        }
    
    # Get Nifty data for RS calculation
    nifty_df = get_nifty_data()
    
    # Calculate technical indicators
    stock_df = calculate_ma(stock_df)
    
    # Calculate RS
    rs = calculate_rs(stock_df, nifty_df)
    
    # Check cup with handle pattern
    has_pattern, pattern_data = identify_cup_with_handle(stock_df)
    
    # Check earnings growth
    has_earnings_growth, eps_growth = check_earnings_growth(fundamentals_df, symbol)
    
    # Set entry, target and stop loss
    entry, target, stop_loss = set_target_sl(stock_df, pattern_data if has_pattern else None)
    
    # Count how many criteria are met
    criteria_met = 0
    total_criteria = 5
    
    # Check if price > 200-day MA
    price_above_ma = False
    if 'MA_200' in stock_df.columns and not pd.isna(stock_df['MA_200'].iloc[-1]):
        price_above_ma = stock_df['Close'].iloc[-1] > stock_df['MA_200'].iloc[-1]
        if price_above_ma:
            criteria_met += 1
    
    # Check RS > 70
    if rs > 70:
        criteria_met += 1
    
    # Check cup with handle pattern
    if has_pattern:
        criteria_met += 1
    
    # Check earnings growth
    if has_earnings_growth:
        criteria_met += 1
    
    # Check if in strong sector
    strong_sectors = get_sector_strength()
    stock_sector = None
    for i, stock_info in fundamentals_df.iterrows():
        if stock_info['Symbol'] == symbol:
            stock_sector = stock_info.get('Sector', None)
            break
    
    in_strong_sector = False
    if stock_sector:
        top_sectors = [s['sector'] for s in strong_sectors[:3]]
        in_strong_sector = any(sector in stock_sector.upper() for sector in top_sectors)
        if in_strong_sector:
            criteria_met += 1
    
    # Prepare result
    result = {
        'valid': criteria_met >= 3,  # Meet at least 3 criteria
        'symbol': symbol,
        'entry': entry,
        'target': target,
        'stop_loss': stop_loss,
        'rs': rs,
        'price_above_ma': price_above_ma,
        'has_pattern': has_pattern,
        'eps_growth': eps_growth if has_earnings_growth else 0,
        'in_strong_sector': in_strong_sector,
        'criteria_met': criteria_met,
        'total_criteria': total_criteria
    }
    
    return result

def get_monthly_picks(fundamentals_df=None, top_n=5):
    """Generate monthly stock picks based on CAN SLIM criteria"""
    if fundamentals_df is None or fundamentals_df.empty:
        st.error("No fundamental data available. Please upload data first.")
        return []
    
    # Get all symbols from the fundamentals data
    symbols = fundamentals_df['Symbol'].unique().tolist()
    
    # Validate each stock
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, symbol in enumerate(symbols):
        progress = (i + 1) / len(symbols)
        progress_bar.progress(progress)
        status_text.text(f"Analyzing {symbol}... ({i+1}/{len(symbols)})")
        
        result = validate_stock(symbol, fundamentals_df)
        if result['valid']:
            results.append(result)
    
    progress_bar.empty()
    status_text.empty()
    
    # Sort by RS score
    results.sort(key=lambda x: x['rs'], reverse=True)
    
    # Take top N results
    top_picks = results[:top_n]
    
    # Save to session state
    st.session_state['monthly_picks'] = top_picks
    
    # Save timestamp
    st.session_state['last_scan_date'] = datetime.now().strftime("%d-%b-%Y %H:%M")
    
    return top_picks

def monitor_portfolio():
    """Monitor current portfolio and send alerts if needed"""
    if 'portfolio' not in st.session_state or not st.session_state['portfolio']:
        return []
    
    portfolio = st.session_state['portfolio']
    updated_portfolio = []
    alerts = []
    
    for stock in portfolio:
        symbol = stock['symbol']
        entry_price = stock['entry']
        target = stock['target']
        stop_loss = stock['stop_loss']
        
        # Get current price
        stock_df = get_stock_data(symbol, period="5d")
        if stock_df.empty:
            stock['current_price'] = entry_price
            stock['pl_percent'] = 0
            stock['status'] = 'Unknown'
            updated_portfolio.append(stock)
            continue
        
        current_price = stock_df['Close'].iloc[-1]
        
        # Calculate P&L
        pl_percent = ((current_price - entry_price) / entry_price) * 100
        
        # Update stock info
        stock['current_price'] = current_price
        stock['pl_percent'] = pl_percent
        
        # Check for alerts
        if current_price <= stop_loss:
            stock['status'] = 'Stopped Out'
            alerts.append({
                'type': 'sl_hit',
                'symbol': symbol,
                'price': current_price,
                'stop_loss': stop_loss,
                'pl_percent': pl_percent
            })
        elif current_price <= stop_loss * 1.005:
            stock['status'] = 'Near Stop Loss'
            alerts.append({
                'type': 'sl_warning',
                'symbol': symbol,
                'price': current_price,
                'stop_loss': stop_loss,
                'buffer': current_price - stop_loss
            })
        elif current_price >= target:
            stock['status'] = 'Target Hit'
            alerts.append({
                'type': 'target_hit',
                'symbol': symbol,
                'price': current_price,
                'target': target,
                'pl_percent': pl_percent
            })
        else:
            stock['status'] = 'Active'
        
        updated_portfolio.append(stock)
    
    # Update portfolio in session state
    st.session_state['portfolio'] = updated_portfolio
    
    # Send alerts if needed
    if 'email_recipient' in st.session_state and st.session_state['email_recipient']:
        for alert in alerts:
            if alert['type'] == 'sl_hit':
                subject = f"🔴 STOP LOSS HIT: {alert['symbol']} @ ₹{alert['price']:.2f}"
                body = f"Your position in {alert['symbol']} has been stopped out.\n\n"
                body += f"Stop Loss: ₹{alert['stop_loss']:.2f}\n"
                body += f"P&L: {alert['pl_percent']:.2f}%\n"
                send_email_alert(st.session_state['email_recipient'], subject, body)
            
            elif alert['type'] == 'sl_warning':
                subject = f"🟠 STOP LOSS WARNING: {alert['symbol']} @ ₹{alert['price']:.2f}"
                body = f"{alert['symbol']} is ₹{alert['buffer']:.2f} away from Stop Loss!\n\n"
                body += f"Current: ₹{alert['price']:.2f}\n"
                body += f"Stop Loss: ₹{alert['stop_loss']:.2f}\n"
                send_email_alert(st.session_state['email_recipient'], subject, body)
            
            elif alert['type'] == 'target_hit':
                subject = f"🟢 TARGET HIT: {alert['symbol']} @ ₹{alert['price']:.2f}"
                body = f"Your position in {alert['symbol']} has reached its target.\n\n"
                body += f"Target: ₹{alert['target']:.2f}\n"
                body += f"P&L: {alert['pl_percent']:.2f}%\n"
                send_email_alert(st.session_state['email_recipient'], subject, body)
    
    return updated_portfolio, alerts

def create_stock_chart(symbol, days=90):
    """Create a stock chart with entry, target, and stop loss levels"""
    stock_df = get_stock_data(symbol, period="1y")
    
    if stock_df.empty:
        return None
    
    # Get the last N days
    stock_df = stock_df.iloc[-days:]
    
    # Find the stock in the portfolio
    entry_price, target_price, stop_loss = None, None, None
    if 'portfolio' in st.session_state:
        for stock in st.session_state['portfolio']:
            if stock['symbol'] == symbol:
                entry_price = stock['entry']
                target_price = stock['target']
                stop_loss = stock['stop_loss']
                break
    
    # Create the chart
    fig = go.Figure()
    
    # Add candlestick trace
    fig.add_trace(go.Candlestick(
        x=stock_df.index,
        open=stock_df['Open'],
        high=stock_df['High'],
        low=stock_df['Low'],
        close=stock_df['Close'],
        name=symbol
    ))
    
    # Add entry, target and stop loss lines if available
    if entry_price:
        fig.add_hline(y=entry_price, line_width=1, line_color="blue", 
                      annotation_text="Entry", annotation_position="right")
    
    if target_price:
        fig.add_hline(y=target_price, line_width=1, line_color="green", 
                      annotation_text="Target", annotation_position="right")
    
    if stop_loss:
        fig.add_hline(y=stop_loss, line_width=1, line_color="red", 
                      annotation_text="Stop Loss", annotation_position="right")
    
    # Update layout
    fig.update_layout(
        title=f"{symbol} Price Chart",
        xaxis_title="Date",
        yaxis_title="Price (₹)",
        height=500,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    
    return fig

def process_fundamentals_csv(uploaded_file):
    """Process uploaded fundamentals CSV"""
    try:
        # Read CSV
        df = pd.read_csv(uploaded_file)
        
        # Minimum required columns
        required_cols = ['Symbol']
        
        # Check if required columns are present
        for col in required_cols:
            if col not in df.columns:
                st.error(f"Missing required column: {col}")
                return None
        
        # Add EPS Growth column if not present
        if 'EPS_Growth_1Y' not in df.columns:
            st.warning("EPS Growth column not found. Some features may not work correctly.")
        
        return df
    
    except Exception as e:
        st.error(f"Error processing CSV: {e}")
        return None

# ----- App UI -----

def main():
    # Initialize session state
    if 'portfolio' not in st.session_state:
        st.session_state['portfolio'] = []
    
    if 'monthly_picks' not in st.session_state:
        st.session_state['monthly_picks'] = []
    
    if 'fundamentals_df' not in st.session_state:
        st.session_state['fundamentals_df'] = None
    
    if 'last_scan_date' not in st.session_state:
        st.session_state['last_scan_date'] = None
    
    # App title and description
    st.title("🚀 CAN SLIM Trading App")
    
    # Create tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Monthly Picks", 
        "💼 Portfolio Tracker", 
        "🔍 Stock Validator", 
        "📈 Sector Analysis",
        "⚙️ Settings"
    ])
    
    # ----- Monthly Picks Tab -----
    with tab1:
        st.header("Monthly CAN SLIM Stock Scanner")
        
        # Last scan date
        if st.session_state['last_scan_date']:
            st.info(f"Last scan: {st.session_state['last_scan_date']}")
        
        # File uploader for fundamentals data
        uploaded_file = st.file_uploader("Upload fundamentals data (CSV from Screener.in)", type="csv")
        
        if uploaded_file:
            # Process the uploaded file
            fundamentals_df = process_fundamentals_csv(uploaded_file)
            if fundamentals_df is not None:
                st.session_state['fundamentals_df'] = fundamentals_df
                st.success(f"Loaded data for {len(fundamentals_df)} stocks")
        
        # Run scan button
        col1, col2 = st.columns([1, 3])
        with col1:
            num_picks = st.number_input("Number of top picks", min_value=1, max_value=10, value=5)
        
        with col2:
            scan_button = st.button("🔍 Run Monthly Scan")
        
        if scan_button:
            if st.session_state['fundamentals_df'] is None:
                st.error("Please upload fundamentals data first")
            else:
                with st.spinner("Scanning stocks..."):
                    picks = get_monthly_picks(st.session_state['fundamentals_df'], top_n=num_picks)
                
                if picks:
                    st.success(f"Found {len(picks)} stocks matching CAN SLIM criteria")
                else:
                    st.warning("No stocks matching CAN SLIM criteria found")
        
        # Display monthly picks
        if st.session_state['monthly_picks']:
            st.subheader(f"[{datetime.now().strftime('%B %Y')} PICKS]")
            
            for i, pick in enumerate(st.session_state['monthly_picks']):
                col1, col2, col3 = st.columns([2, 2, 1])
                
                with col1:
                    st.write(f"**{i+1}. {pick['symbol']} (₹{pick['entry']:.2f})**")
                    st.caption(f"RS: {pick['rs']}, EPS Growth: {pick['eps_growth']:.1f}%")
                
                with col2:
                    st.write(f"Target: ₹{pick['target']:.2f} | SL: ₹{pick['stop_loss']:.2f}")
                    criteria = []
                    if pick['price_above_ma']:
                        criteria.append("Price > 200MA")
                    if pick['has_pattern']:
                        criteria.append("Cup-with-Handle")
                    if pick['eps_growth'] > 15:
                        criteria.append("Strong EPS")
                    st.caption(" | ".join(criteria))
                
                with col3:
                    if st.button(f"Add to Portfolio", key=f"add_{pick['symbol']}"):
                        # Check if already in portfolio
                        symbols = [s['symbol'] for s in st.session_state['portfolio']]
                        if pick['symbol'] not in symbols:
                            # Add to portfolio
                            portfolio_item = {
                                'symbol': pick['symbol'],
                                'entry': pick['entry'],
                                'target': pick['target'],
                                'stop_loss': pick['stop_loss'],
                                'current_price': pick['entry'],
                                'pl_percent': 0,
                                'status': 'Active',
                                'date_added': datetime.now().strftime("%d-%b-%Y")
                            }
                            st.session_state['portfolio'].append(portfolio_item)
                            st.success(f"Added {pick['symbol']} to portfolio")
                            
                            # Send email alert if email is configured
                            if 'email_recipient' in st.session_state and st.session_state['email_recipient']:
                                subject = f"🟢 NEW ENTRY: {pick['symbol']} @ ₹{pick['entry']:.2f}"
                                body = f"- Target: ₹{pick['target']:.2f} (+{((pick['target']/pick['entry'])-1)*100:.1f}%)\n"
                                body += f"- Stop: ₹{pick['stop_loss']:.2f} (-{((1-pick['stop_loss']/pick['entry']))*100:.1f}%)\n"
                                body += f"- Chart: https://in.tradingview.com/chart/?symbol=NSE:{pick['symbol']}\n"
                                
                                send_email_alert(st.session_state['email_recipient'], subject, body)
                        else:
                            st.warning(f"{pick['symbol']} already in portfolio")
                
                st.divider()
    
    # ----- Portfolio Tracker Tab -----
    with tab2:
        st.header("Portfolio Tracker")
        
        # Update portfolio button
        refresh = st.button("🔄 Refresh Portfolio (15-min delayed)")
        
        if refresh:
            with st.spinner("Updating portfolio..."):
                updated_portfolio, alerts = monitor_portfolio()
            
            if alerts:
                for alert in alerts:
                    if alert['type'] == 'sl_hit':
                        st.error(f"🔴 STOP LOSS HIT: {alert['symbol']} @ ₹{alert['price']:.2f} ({alert['pl_percent']:.2f}%)")
                    elif alert['type'] == 'sl_warning':
                        st.warning(f"🟠 STOP LOSS WARNING: {alert['symbol']} is ₹{alert['buffer']:.2f} away from SL!")
                    elif alert['type'] == 'target_hit':
                        st.success(f"🟢 TARGET HIT: {alert['symbol']} @ ₹{alert['price']:.2f} ({alert['pl_percent']:.2f}%)")
        
        # Display portfolio
        if st.session_state['portfolio']:
            # Create a dataframe for the portfolio
            portfolio_data = []
            for stock in st.session_state['portfolio']:
                portfolio_data.append({
                    'Symbol': stock['symbol'],
                    'Entry': f"₹{stock['entry']:.2f}",
                    'Current': f"₹{stock['current_price']:.2f}",
                    'Target': f"₹{stock['target']:.2f}",
                    'Stop Loss': f"₹{stock['stop_loss']:.2f}",
                    'P&L': f"{stock['pl_percent']:.2f}%",
                    'Status': stock['status'],
                    'Added': stock['date_added']
                })
            
            df = pd.DataFrame(portfolio_data)
            st.dataframe(df, use_container_width=True)
            
            # Show charts for portfolio stocks
            selected_stock = st.selectbox("Select stock to view chart", 
                                         [s['symbol'] for s in st.session_state['portfolio']])
            
            if selected_stock:
                fig = create_stock_chart(selected_stock)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
                
                # Add option to remove from portfolio
                if st.button("🗑️ Remove from Portfolio", key=f"remove_{selected_stock}"):
                    st.session_state['portfolio'] = [s for s in st.session_state['portfolio'] 
                                                   if s['symbol'] != selected_stock]
                    st.success(f"Removed {selected_stock} from portfolio")
                    st.experimental_rerun()
        else:
            st.info("Your portfolio is empty. Add stocks from the Monthly Picks tab.")
    
    # ----- Stock Validator Tab -----
    with tab3:
        st.header("Stock Validator")
        st.write("Check if a stock meets CAN SLIM criteria")
        
        # Input for stock symbol
        stock_symbol = st.text_input("Enter NSE Symbol (e.g., TATASTEEL)", key="validator_symbol")
        
        validate_button = st.button("Validate Stock")
        
        if validate_button and stock_symbol:
            with st.spinner(f"Analyzing {stock_symbol}..."):
                result = validate_stock(stock_symbol, st.session_state['fundamentals_df'])
                
                if result['valid']:
                    st.success(f"✅ {stock_symbol}: Meets {result['criteria_met']}/{result['total_criteria']} CAN SLIM criteria")
                    
                    # Display details
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write(f"Entry: ₹{result['entry']:.2f}")
                        st.write(f"Target: ₹{result['target']:.2f}")
                        st.write(f"Stop Loss: ₹{result['stop_loss']:.2f}")
                    
                    with col2:
                        st.write(f"RS: {result['rs']}")
                        st.write(f"EPS Growth: {result['eps_growth']:.1f}%")
                        st.write(f"Pattern: {'Cup-with-Handle' if result['has_pattern'] else 'None'}")
                    
                    st.caption("⚠️ This is for educational purposes only. Consult your financial advisor.")
                    
                    # Option to add to portfolio
                    if st.button("Add to Portfolio", key=f"add_validated_{stock_symbol}"):
                        # Check if already in portfolio
                        symbols = [s['symbol'] for s in st.session_state['portfolio']]
                        if stock_symbol not in symbols:
                            # Add to portfolio
                            portfolio_item = {
                                'symbol': stock_symbol,
                                'entry': result['entry'],
                                'target': result['target'],
                                'stop_loss': result['stop_loss'],
                                'current_price': result['entry'],
                                'pl_percent': 0,
                                'status': 'Active',
                                'date_added': datetime.now().strftime("%d-%b-%Y")
                            }
                            st.session_state['portfolio'].append(portfolio_item)
                            st.success(f"Added {stock_symbol} to portfolio")
                        else:
                            st.warning(f"{stock_symbol} already in portfolio")
                else:
                    st.warning(f"❌ {stock_symbol} meets only {result['criteria_met']}/{result['total_criteria']} criteria")
                
                # Show chart
                fig = create_stock_chart(stock_symbol)
                if fig:
                    st.plotly_chart(fig, use_container_width=True)
    
    # ----- Sector Analysis Tab -----
    with tab4:
        st.header("Sector Strength Analyzer")
        
        analyze_button = st.button("Analyze Sector Strength")
        
        if analyze_button:
            with st.spinner("Analyzing sector strength..."):
                sector_strength = get_sector_strength()
                
                if sector_strength:
                    st.subheader("💪 Top Sectors for Next 3 Months:")
                    
                    # Create a dataframe for sector strength
                    sector_data = []
                    for i, sector in enumerate(sector_strength):
                        sector_data.append({
                            'Rank': i + 1,
                            'Sector': sector['sector'],
                            'RS': sector['rs'],
                            'Price > 200MA': "✅" if sector['price_above_ma'] else "❌",
                            'Score': sector['score']
                        })
                    
                    df = pd.DataFrame(sector_data)
                    st.dataframe(df, use_container_width=True)
                    
                    # Display top 2 sectors
                    st.text(f"""
                    💪 Top Sectors for Next 3 Months:
                    1. {sector_strength[0]['sector']} (RS: {sector_strength[0]['rs']})
                    2. {sector_strength[1]['sector']} (RS: {sector_strength[1]['rs']})
                    """)
                else:
                    st.error("Failed to analyze sector strength.")
    
    # ----- Settings Tab -----
    with tab5:
        st.header("Settings")
        
        # Email settings
        st.subheader("Email Alert Settings")
        
        email_recipient = st.text_input("Your Email (to receive alerts)", 
                                       value=st.session_state.get("email_recipient", ""))
        
        email_sender = st.text_input("Sender Email Address (Gmail recommended)", 
                                    value=st.session_state.get("email_sender", ""))
        
        email_password = st.text_input("App Password (not your regular password)", 
                                      type="password",
                                      value=st.session_state.get("email_password", ""),
                                      help="For Gmail, generate an App Password in your Google Account settings")
        
        if st.button("Save Email Settings"):
            st.session_state['email_recipient'] = email_recipient
            st.session_state['email_sender'] = email_sender
            st.session_state['email_password'] = email_password
            st.success("Email settings saved")
            
            # Test email
            if email_recipient and email_sender and email_password:
                test_result = send_email_alert(
                    email_recipient,
                    "🚀 CAN SLIM Trading App - Test Email",
                    "This is a test email from your CAN SLIM Trading App. If you received this, your email settings are working correctly!"
                )
                
                if test_result:
                    st.success("Test email sent successfully!")
                else:
                    st.error("Failed to send test email. Please check your settings.")
        
        # Help and info
        st.subheader("Troubleshooting Email Alerts")
        
        st.markdown("""
        ### Common Issues and Solutions

        1. **Not receiving alerts**
           - Check your spam/junk folder
           - Add the sender's email to your contacts/safe senders list
           - Verify you entered your email correctly
           - Check if your email provider is blocking the alerts

        2. **Gmail setup**
           - Use an App Password, not your regular password
           - Enable 2-Step Verification in your Google Account
           - Generate an App Password under Security settings

        3. **Other email services**
           - Yahoo and Outlook are supported but may require special setup
           - Some email providers block automated emails
           
        4. **"Less secure apps" issue**
           - Gmail no longer supports "Less secure apps" setting
           - You MUST use an App Password instead
        """)

if __name__ == "__main__":
    main()