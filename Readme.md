📂 Database Backup Service
A robust, automated backup solution for PostgreSQL & MySQL

🚀 Features
✅ Automated Backups (SQL & CSV formats)
✅ Scheduled Backups (hourly/daily/weekly)
✅ Backup Retention (keeps last 3 backups)
✅ Web API (Flask-based, port 5002)
✅ Windows Service Control (start/stop PostgreSQL/MySQL)
✅ Cross-Platform (Windows, Linux, macOS)

🛠 Installation
1. Clone the Repository
git clone [https://github.com/IRamadi/POSTGRESQL-MYSQL-BACKUPSYS-PYTHON.git](https://github.com/IRamadi/POSTGRESQL-MYSQL-BACKUPSYS-PYTHON.git)
cd POSTGRESQL-MYSQL-BACKUPSYS-PYTHON

Create a virtual environment (recommended):

python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

2. Install Dependencies
pip install -r requirements.txt
3. Install Database Tools (If Missing)

For PostgreSQL
# Linux (Debian/Ubuntu)
sudo apt-get install postgresql-client

# macOS (Homebrew)
brew install postgresql
For MySQL

# Linux (Debian/Ubuntu)
sudo apt-get install mysql-client

# macOS (Homebrew)
brew install mysql-client
🏃 Running the Service
Basic Usage

python db_backup_service.py
➡ Access API: http://localhost:5002

Run in Background (Linux/macOS)

nohup python app.py > backup_service.log 2>&1 &
Run as a Windows Service
Install pywin32:

pip install pywin32
Use NSSM (Non-Sucking Service Manager):

powershell
nssm install "Database Backup Service" "C:\Python\python.exe" "C:\path\to\app.py"
nssm start "Database Backup Service"
🔌 API Endpoints
Endpoint	Method	Description
/	GET	Service status
/connect	POST	Connect to a database
/disconnect	POST	Disconnect from DB
/create_backup	POST	Create a backup
/restore_backup	POST	Restore a backup
/list_backups	GET	List available backups
/set_schedule	POST	Set backup schedule
/service_control	POST	Control DB service (Windows)
📌 See Full API Documentation for details.

⚙ Configuration
Config file (db_backup_config.ini) is auto-generated on first run:

ini
[Database]
type = postgresql
host = localhost
port = 5432
name = mydb
user = admin
password = password

[Backup]
location = /backups
format = sql
schedule = daily
📜 Backup Policy
Keeps only the last 3 backups (oldest auto-deleted).

Backup naming: Backup_{db_name}_{YYYYMMDD_HHMMSS}.sql (or .zip for CSV).

📂 Logging
Logs are stored in:

logs/db_backup_service.log
Rotates logs (max 5 files, 1MB each).

🔧 Troubleshooting
Issue	Fix
"pg_dump not found"	Install PostgreSQL client tools.
"Access denied" (Windows)	Run as Administrator.
Backup fails	Check logs in logs/.
API not responding	Ensure service is running (http://localhost:5002).


🌐 API Endpoints Reference
Endpoint	Method	Description	Example Request Body
/	GET	Check service status ({"status": "running"})	-
/connect	POST	Connect to PostgreSQL/MySQL	{"db_type": "postgresql", "host": "localhost", "port": "5432", "db_name": "mydb", "user": "admin", "password": "pass"}
/disconnect	POST	Disconnect from the current database	-
/create_backup	POST	Create a new backup (SQL or CSV)	{"backup_dir": "/backups", "format": "sql"}
/restore_backup	POST	Restore a backup file	{"backup_file": "/backups/Backup_mydb_20240101.sql"}
/list_backups	GET	List available backups in a directory (query param: ?backup_dir=/backups)	-
/set_schedule	POST	Set backup schedule (hourly, daily, weekly, disabled)	{"schedule": "daily"}
/service_control	POST	(Windows only) Start/stop/restart PostgreSQL/MySQL services	{"service_type": "postgresql", "action": "restart"}
🔄 Example API Usage
1. Connect to a PostgreSQL Database
   
curl -X POST http://localhost:5002/connect \
  -H "Content-Type: application/json" \
  -d '{
    "db_type": "postgresql",
    "host": "localhost",
    "port": "5432",
    "db_name": "mydb",
    "user": "admin",
    "password": "password"
  }'
3. Create a Backup (SQL Format)
bash
curl -X POST http://localhost:5002/create_backup \
  -H "Content-Type: application/json" \
  -d '{
    "backup_dir": "/backups",
    "format": "sql"
  }'
4. List Backups

curl "http://localhost:5002/list_backups?backup_dir=/backups"
5. Restore a Backup

curl -X POST http://localhost:5002/restore_backup \
  -H "Content-Type: application/json" \
  -d '{
    "backup_file": "/backups/Backup_mydb_20240101.sql"
  }'
🔍 How the API Works
The script runs a Flask server on port 5002 by default.

All endpoints accept/return JSON.

Error handling: If something fails, the API returns a 400/500 error with details.

📌 Key Notes
Authentication: The API has no built-in auth (for simplicity). If exposed to the internet, secure it with:

Firewall rules (allow only trusted IPs).

Reverse proxy (NGINX/Apache with HTTPS + Basic Auth).

Or modify app.py to add Flask-based authentication.

Windows Service Control:

Only works on Windows (uses pywin32).

Requires admin privileges to manage services.


🔧 Fixing Missing Database Tools

For PostgreSQL (Windows):
# Download and install PostgreSQL (includes command line tools)
https://www.postgresql.org/download/windows/
in powershell
# Add to PATH (example - adjust for your version):
[Environment]::SetEnvironmentVariable("PATH", "$env:PATH;C:\Program Files\PostgreSQL\16\bin", "Machine")

For MySQL (Windows):
# Download and install MySQL Community Server
https://dev.mysql.com/downloads/installer/
in powershell
# Add to PATH (example):
[Environment]::SetEnvironmentVariable("PATH", "$env:PATH;C:\Program Files\MySQL\MySQL Server 8.0\bin", "Machine")

For Linux (Debian/Ubuntu):
# PostgreSQL tools
sudo apt-get install postgresql-client

# MySQL tools
sudo apt-get install mysql-client

🔒 Production Deployment Warning
Recommended Production Setup:
Use Waitress (for Windows)

pip install waitress
waitress-serve --host=0.0.0.0 --port=5002 db_backup_service:app
Or Gunicorn (for Linux)

pip install gunicorn
gunicorn -b 0.0.0.0:5002 db_backup_service:app
Verification Steps
Check if tools are now accessible:

# For PostgreSQL
pg_dump --version

# For MySQL 
mysqldump --version
Restart your backup service after installing the tools.

Additional Recommendations
Configure Firewall to only allow access from trusted IPs

Set up HTTPS using a reverse proxy like Nginx

Implement authentication for the web interface

The service is now running and accessible at:

Local: http://127.0.0.1:5002

Network: http://yourip:5002
