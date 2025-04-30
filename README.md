# CAN SLIM Trading App - Deployment Guide

## Prerequisites
- A computer with internet connection
- Basic knowledge of command line operations (minimal commands required)
- No coding knowledge required for deployment

## Option 1: Local Deployment (Easiest)

### Step 1: Install Python
1. Download Python from [python.org](https://www.python.org/downloads/) (version 3.9+ recommended)
2. During installation, check the box "Add Python to PATH"
3. Verify installation by opening a command prompt/terminal and typing:
   ```
   python --version
   ```

### Step 2: Download the App
1. Download the app code from the provided zip file or repository
2. Extract the files to a folder on your computer

### Step 3: Install Required Packages
1. Open a command prompt/terminal
2. Navigate to the folder where you extracted the app
3. Run the following command:
   ```
   pip install -r requirements.txt
   ```
   This will install all necessary packages (including Streamlit, NSEPy, yfinance, etc.)

### Step 4: Run the App
1. In the same command prompt/terminal, run:
   ```
   streamlit run app.py
   ```
2. Your default web browser will automatically open with the app running
3. The app will be accessible at http://localhost:8501

## Option 2: Cloud Deployment (Vercel)

### Step 1: Create a GitHub Account
1. Sign up for a free account at [github.com](https://github.com)

### Step 2: Create a New Repository
1. Click the "+" icon in the top-right of GitHub
2. Select "New repository"
3. Name your repository (e.g., "canslim-trading-app")
4. Choose "Public" and click "Create repository"

### Step 3: Upload App Files
1. Click "uploading an existing file"
2. Drag and drop all the app files or select them from your computer
3. Click "Commit changes"

### Step 4: Sign Up for Vercel
1. Go to [vercel.com](https://vercel.com) and sign up using your GitHub account
2. Authorize Vercel to access your GitHub repositories

### Step 5: Deploy to Vercel
1. In Vercel dashboard, click "Add New..." then "Project"
2. Select your GitHub repository with the CAN SLIM app
3. In the configuration screen:
   - Framework preset: Select "Streamlit"
   - Build Command: `pip install -r requirements.txt`
   - Output Directory: Leave default
4. Click "Deploy"

### Step 6: Access Your App
1. After deployment completes, Vercel will provide a URL to access your app
2. Your app is now available online and can be accessed from anywhere

## Setting Up Email Alerts

### For Gmail
1. Go to your Google Account settings
2. Enable 2-Step Verification
3. Search for "App passwords" in your Google Account
4. Create a new app password
5. Use this password in the app's email settings (not your regular Gmail password)

### For Other Email Providers
1. Yahoo and Outlook are supported
2. Check your email provider's documentation for "app password" or "SMTP access"
3. Some email providers might block automated emails

## Troubleshooting

### App Won't Start
1. Verify Python is installed correctly
2. Make sure all dependencies are installed using:
   ```
   pip install -r requirements.txt
   ```
3. Check for error messages in the terminal

### Email Alerts Not Working
1. Test your email settings in the app's Settings tab
2. For Gmail:
   - Verify you're using an App Password, not your regular password
   - Check that 2-Step Verification is enabled
3. Check your spam/junk folder for test emails
4. Some email providers may block automated emails

### Data Not Loading
1. Ensure you have an active internet connection
2. NSEPy may have temporary outages; the app will fall back to yfinance
3. Verify your CSV file format matches the expected format

## Updating Your App
1. For local installation:
   - Replace the app.py file with the new version
   - Run `pip install -r requirements.txt` to update dependencies
2. For Vercel deployment:
   - Update the files in your GitHub repository
   - Vercel will automatically redeploy the updated app

## Need More Help?
If you encounter issues not covered in this guide, please check the project's GitHub repository for additional documentation and support resources.

## Free Data Sources
The app uses these free data sources:
- NSEPy for price data (with yfinance as fallback)
- Screener.in CSV export for fundamentals (manual upload required)
