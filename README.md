# 🛡️ RansomwareGuard – Smart Backup and Instant Recovery System

## 📌 Overview

RansomwareGuard is a Python-based desktop security application designed to detect suspicious file activity and protect user files against potential ransomware threats. The application monitors a selected folder, identifies unusual file activity, sends alerts through a Telegram bot, and automatically backs up and restores files using a smart backup vault.

The system also includes risk scoring, suspicious process monitoring, network connectivity monitoring, and a graphical user interface for managing protection settings.

## 🛠️ Technologies Used

- Python
- Tkinter
- CustomTkinter
- PyWin32
- Psutil
- Telegram Bot API
- Shutil and Zipfile
- Threading
- JSON Configuration
- PyInstaller

## ✨ Features

- Monitor file and folder activities in real time
- Detect suspicious file creation, modification, deletion, and renaming
- Calculate risk scores based on file activity
- Display system security alerts through a graphical interface
- Send ransomware alerts through a Telegram bot
- Provide ALLOW, KILL + SHUTDOWN, and RESTORE FILES actions
- Create an initial full backup of the monitored folder
- Synchronize new and modified files with the backup vault
- Automatically restore deleted files from the backup vault
- Support recursive monitoring of subdirectories
- Create timestamped ZIP backups
- Monitor network connectivity and trigger security responses when connectivity is lost
- Retry selected file operations when temporary access errors occur
- Maintain application logs for monitoring and troubleshooting
- Package the application as a standalone Windows executable

## 🔄 Workflow

1. Launch the RansomwareGuard desktop application.
2. Configure the Telegram bot credentials and select a folder to monitor.
3. Start the monitoring engine.
4. Create an initial backup of the selected folder.
5. Monitor file system events and calculate suspicious activity risk scores.
6. Generate local notifications and Telegram alerts when suspicious activity is detected.
7. Allow the authorized operator to choose an appropriate response.
8. Back up changed files and restore deleted files from the backup vault when possible.
9. Record security events and operational status in the application logs.

## 🚀 How to Run

### 1. Install Python

Install Python 3.12 or another compatible Python version on Windows.

### 2. Install Required Packages

Open Command Prompt or PowerShell in the project directory and run:

```bash
pip install pywin32 psutil pyTelegramBotAPI plyer customtkinter
```

### 3. Configure the Application

- Open the application.
- Enter your Telegram bot token and chat ID.
- Select the folder you want to monitor.
- Save the configuration if required.

Keep your Telegram credentials private. Do not upload `config.json` containing real credentials to a public GitHub repository.

### 4. Run the Application

If your Python file is named `app.py`, run:

```bash
python app.py
```

If you keep the original filename, use:

```bash
python "app_v534_professional (2).py"
```

### 5. Build a Windows Executable

Install PyInstaller:

```bash
pip install pyinstaller
```

Build the executable:

```bash
pyinstaller --onefile --noconsole --name RansomwareGuard "app_v534_professional (2).py"
```

The generated executable will normally be available in the `dist/` directory.

## 📁 Project Structure

```text
RansomwareGuard/
│
├── app.py
├── README.md
├── requirements.txt
├── .gitignore
└── config.json
```

*Note: This is a suggested project structure. Keep configuration files containing secrets out of the public repository.*

## 🎯 Outcome

RansomwareGuard aims to improve individual-user file protection by combining real-time file monitoring, suspicious activity detection, Telegram-based alerts, automatic backup synchronization, and file restoration. The application provides a centralized desktop interface to monitor security events and manage responses to potential ransomware activity.

## 🔮 Future Enhancements

- Improve ransomware detection accuracy
- Add backup integrity verification
- Introduce secure configuration management
- Add detailed security reports and activity summaries
- Enhance recovery testing and backup management

## 📄 License

This project is intended for educational and research purposes. Add a specific open-source license if you plan to distribute the project publicly.
