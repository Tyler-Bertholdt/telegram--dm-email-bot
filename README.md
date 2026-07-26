
# 🤖 Telegram Gemini Gmail Assistant

A secure, intelligent Telegram bot that manages your Gmail inbox using **Google's Gemini API** with **Human-in-the-Loop confirmation**. Type natural language commands like *"Archive all newsletters from last week"* or *"Delete the last 5 unread emails"*, review the parsed action card, and approve or cancel it right from your Telegram chat.

---

## 🗺️ Architecture Blueprint

1. **Incoming Watcher / Intent Parsing (Telegram $\rightarrow$ Gemini):** You send a natural language command to your Telegram bot. Gemini uses native function calling (`gemini-2.5-flash`) to parse your text and structure it into exact API parameters.
2. **Confirmation State Machine:** Before touching your inbox, the bot sends an interactive Telegram message with a preview of the pending action and inline buttons.
3. **Execution (Gmail API):** Once you tap **Approve**, the backend executes the Gmail API call safely.

---

## 📂 Project Structure

```text
gemini-mail-bot/
│
├── .env                 # Secret API keys and tokens (Never commit this!)
├── .gitignore           # Git ignore rules for security
├── requirements.txt     # Python package dependencies
├── main.py              # Telegram bot entry point & state machine
├── gmail_service.py     # Gmail API authentication and execution logic
└── gemini_parser.py     # Gemini function calling and intent parsing engine

```

---

## 🛠️ Tech Stack & Requirements

* **Python 3.10+**
* **Google GenAI SDK** (`google-genai`)
* **Python Telegram Bot** (`python-telegram-bot`)
* **Google API Client** (`google-api-python-client`)

---

## 🚀 Getting Started & Installation

### 1. Clone the Repository

```bash
git clone [https://github.com/YourUsername/YourRepoName.git](https://github.com/YourUsername/YourRepoName.git)
cd YourRepoName

```

### 2. Set Up a Virtual Environment

```bash
python -m venv venv

# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

```

### 3. Install Dependencies

```bash
pip install -r requirements.txt

```

### 4. Configure Environment Variables

Create a `.env` file in the root directory of your project and add your credentials:

```env
# Gemini API Key (Get yours from Google AI Studio)
GEMINI_API_KEY=your_gemini_api_key_here

# Telegram Bot Token (Get yours from @BotFather on Telegram)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

```

### 5. Set Up Google Cloud / Gmail API Credentials

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable the **Gmail API**.
3. Configure your OAuth consent screen and download your `credentials.json` file into the root project directory.
4. (The first time you run the Gmail service, it will generate a `token.json` file automatically upon authorization).

---

## 🔒 Security Best Practices

* **Never commit your `.env`, `credentials.json`, or `token.json` files.** They are already included in `.gitignore` to prevent accidental public exposure.
* **Human-in-the-Loop:** No email is ever deleted or archived automatically. Every command requires your explicit confirmation via Telegram inline buttons.

---

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

```

```