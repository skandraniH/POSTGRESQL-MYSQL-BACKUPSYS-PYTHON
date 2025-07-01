import os
import sys
import subprocess
import datetime
import time
import traceback
import platform
import csv
import shutil
import warnings
import psycopg2
import pymysql
from configparser import ConfigParser
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, jsonify, request

# Suppress warnings
warnings.filterwarnings("ignore")

# Import service management modules (Windows only)
if platform.system() == 'Windows':
    import win32serviceutil
    import win32service
    import win32con
    import win32api
    import win32process
    import win32event
    try:
        import wmi
    except ImportError:
        wmi = None
import psutil

# Constants
CONFIG_FILE = 'db_backup_config.ini'
MAX_BACKUPS = 3
WEB_INTERFACE_PORT = 5002

class DatabaseBackupService:
    def __init__(self):
        self.connection = None
        self.current_db_type = None
        self.current_postgres_service = None
        self.current_mysql_service = None
        self.pg_dump_path = None
        self.pg_restore_path = None
        self.mysqldump_path = None
        self.mysql_path = None
        self.background_processes = []
        self.scheduler = BackgroundScheduler()
        self.app = Flask(__name__)
        self.setup_logging()
        self.setup_flask_routes()
        
        # Initialize scheduler
        self.scheduler.start()
        self.load_config()
        self.find_database_tools()
        
    def setup_logging(self):
        """Configure logging for the service"""
        log_dir = 'logs'
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        log_file = os.path.join(log_dir, 'db_backup_service.log')
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        
    def setup_flask_routes(self):
        """Set up Flask API endpoints"""
        @self.app.route('/')
        def status():
            return jsonify({
                'status': 'running',
                'database_connected': self.connection is not None,
                'database_type': self.current_db_type,
                'next_backup': self.get_next_backup_time(),
                'scheduler_running': self.scheduler.running
            })
            
        @self.app.route('/connect', methods=['POST'])
        def api_connect():
            data = request.json
            try:
                self.connect_to_db(
                    data.get('db_type'),
                    data.get('host'),
                    data.get('port'),
                    data.get('db_name'),
                    data.get('user'),
                    data.get('password')
                )
                return jsonify({'status': 'success', 'message': 'Connected to database'})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
                
        @self.app.route('/disconnect', methods=['POST'])
        def api_disconnect():
            self.logout_from_db()
            return jsonify({'status': 'success', 'message': 'Disconnected from database'})
            
        @self.app.route('/create_backup', methods=['POST'])
        def api_create_backup():
            data = request.json
            try:
                backup_file = self.create_backup(
                    data.get('backup_dir'),
                    data.get('format', 'sql')
                )
                return jsonify({'status': 'success', 'backup_file': backup_file})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
                
        @self.app.route('/restore_backup', methods=['POST'])
        def api_restore_backup():
            data = request.json
            try:
                self.restore_backup(data.get('backup_file'))
                return jsonify({'status': 'success'})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
                
        @self.app.route('/list_backups', methods=['GET'])
        def api_list_backups():
            backup_dir = request.args.get('backup_dir')
            if not backup_dir:
                return jsonify({'status': 'error', 'message': 'backup_dir parameter required'}), 400
                
            try:
                backups = self.list_backups(backup_dir)
                return jsonify({'status': 'success', 'backups': backups})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
                
        @self.app.route('/set_schedule', methods=['POST'])
        def api_set_schedule():
            data = request.json
            try:
                self.set_schedule(data.get('schedule'))
                return jsonify({'status': 'success'})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
                
        @self.app.route('/service_control', methods=['POST'])
        def api_service_control():
            data = request.json
            service_type = data.get('service_type')
            action = data.get('action')
            
            try:
                if service_type == 'postgresql':
                    if action == 'start':
                        self.start_postgresql_service()
                    elif action == 'stop':
                        self.stop_postgresql_service()
                    elif action == 'restart':
                        self.restart_postgresql_service()
                elif service_type == 'mysql':
                    if action == 'start':
                        self.start_mysql_service()
                    elif action == 'stop':
                        self.stop_mysql_service()
                    elif action == 'restart':
                        self.restart_mysql_service()
                        
                return jsonify({'status': 'success'})
            except Exception as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
    
    def get_next_backup_time(self):
        """Get the next scheduled backup time"""
        jobs = self.scheduler.get_jobs()
        if jobs:
            return jobs[0].next_run_time.strftime('%Y-%m-%d %H:%M:%S')
        return "Not scheduled"
        
    def list_backups(self, backup_dir):
        """List available backups in a directory"""
        if not os.path.isdir(backup_dir):
            raise Exception("Backup directory does not exist")
            
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.startswith("Backup_") and (filename.endswith('.sql') or filename.endswith('.zip')):
                filepath = os.path.join(backup_dir, filename)
                mtime = os.path.getmtime(filepath)
                backups.append({
                    'filename': filename,
                    'path': filepath,
                    'modified': datetime.datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'size': os.path.getsize(filepath)
                })
                
        # Sort by modification time (newest first)
        backups.sort(key=lambda x: x['modified'], reverse=True)
        return backups
        
    def set_schedule(self, schedule):
        """Set the backup schedule"""
        self.scheduler.remove_all_jobs()
        
        if schedule == "disabled":
            return
            
        if schedule == "hourly":
            trigger = CronTrigger(hour="*", minute=0)
        elif schedule == "6hours":
            trigger = CronTrigger(hour="*/6", minute=0)
        elif schedule == "12hours":
            trigger = CronTrigger(hour="*/12", minute=0)
        elif schedule == "daily":
            trigger = CronTrigger(hour=0, minute=0)
        elif schedule == "weekly":
            trigger = CronTrigger(day_of_week="sun", hour=0, minute=0)
        else:
            raise Exception("Invalid schedule")
            
        self.scheduler.add_job(
            self.create_backup,
            trigger=trigger,
            args=[self.config.get('Backup', 'location'), 'sql'],
            next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10)
        )
        
        # Save to config
        self.config['Backup']['schedule'] = schedule
        self.save_config()
        
    def safe_decode(self, byte_data):
        """Safely decode byte data to string"""
        if isinstance(byte_data, str):
            return byte_data
            
        encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        
        for encoding in encodings:
            try:
                return byte_data.decode(encoding)
            except UnicodeDecodeError:
                continue
            except AttributeError:
                return str(byte_data)
                
        try:
            return byte_data.decode('utf-8', errors='replace')
        except:
            return "Unable to decode error message"
    
    def logout_from_db(self):
        """Disconnect from the current database"""
        if self.connection:
            try:
                self.connection.close()
                self.connection = None
                self.current_db_type = None
                self.logger.info("Disconnected from database")
            except Exception as e:
                self.logger.error(f"Error during logout: {str(e)}")
    
    def find_database_tools(self):
        """Find database utilities in the system"""
        if platform.system() == 'Windows':
            pg_versions = ["16", "15", "14", "13", "12", "11", "10", "9.6"]
            pg_paths = [
                rf"C:\Program Files\PostgreSQL\{ver}\bin\pg_dump.exe" for ver in pg_versions
            ] + [
                r"C:\Program Files\PostgreSQL\bin\pg_dump.exe",
                os.path.expandvars(r"%PROGRAMFILES%\PostgreSQL\bin\pg_dump.exe"),
                os.path.expandvars(r"%PROGRAMFILES(x86)%\PostgreSQL\bin\pg_dump.exe")
            ]
            
            mysql_versions = ["8.1", "8.0", "5.7", "5.6"]
            mysql_paths = [
                rf"C:\Program Files\MySQL\MySQL Server {ver}\bin\mysqldump.exe" for ver in mysql_versions
            ] + [
                r"C:\Program Files\MySQL\bin\mysqldump.exe",
                os.path.expandvars(r"%PROGRAMFILES%\MySQL\bin\mysqldump.exe")
            ]
            
            for drive in ["C:", "D:", "E:"]:
                pg_paths.append(rf"{drive}\PostgreSQL\bin\pg_dump.exe")
                mysql_paths.append(rf"{drive}\MySQL\bin\mysqldump.exe")
                
            for path in pg_paths:
                if os.path.exists(path):
                    self.pg_dump_path = path
                    self.pg_restore_path = path.replace("pg_dump.exe", "pg_restore.exe")
                    break
                    
            for path in mysql_paths:
                if os.path.exists(path):
                    self.mysqldump_path = path
                    self.mysql_path = path.replace("mysqldump.exe", "mysql.exe")
                    break
        else:
            for tool in ['pg_dump', 'pg_restore', 'mysqldump', 'mysql']:
                try:
                    path = subprocess.check_output(['which', tool]).decode().strip()
                    if tool == 'pg_dump':
                        self.pg_dump_path = path
                    elif tool == 'pg_restore':
                        self.pg_restore_path = path
                    elif tool == 'mysqldump':
                        self.mysqldump_path = path
                    elif tool == 'mysql':
                        self.mysql_path = path
                except:
                    pass
        
        self.check_environment_paths()
        self.log_tool_status()
    
    def check_environment_paths(self):
        """Check for tools in the system PATH"""
        paths = os.environ['PATH'].split(os.pathsep)
        
        for path in paths:
            if not path.strip():
                continue
                
            path = path.strip('"')
            
            pg_dump = os.path.join(path, "pg_dump.exe" if platform.system() == "Windows" else "pg_dump")
            if not self.pg_dump_path and os.path.exists(pg_dump):
                self.pg_dump_path = pg_dump
                self.pg_restore_path = os.path.join(path, "pg_restore.exe" if platform.system() == "Windows" else "pg_restore")
                
            mysqldump = os.path.join(path, "mysqldump.exe" if platform.system() == "Windows" else "mysqldump")
            if not self.mysqldump_path and os.path.exists(mysqldump):
                self.mysqldump_path = mysqldump
                self.mysql_path = os.path.join(path, "mysql.exe" if platform.system() == "Windows" else "mysql")
    
    def log_tool_status(self):
        """Log the status of found database tools"""
        tools = {
            'pg_dump': self.pg_dump_path,
            'pg_restore': self.pg_restore_path,
            'mysqldump': self.mysqldump_path,
            'mysql': self.mysql_path
        }
        
        for name, path in tools.items():
            if path and os.path.exists(path):
                self.logger.info(f"{name} found at: {path}")
            else:
                self.logger.warning(f"{name} not found")
    
    def connect_to_db(self, db_type, host, port, db_name, user, password):
        """Connect to a database"""
        self.logout_from_db()
        
        if not all([host, db_name, user]):
            raise Exception("Please fill in all required fields")
            
        try:
            if db_type == "postgresql":
                port = port or "5432"
                self.connection = psycopg2.connect(
                    host=host,
                    port=port,
                    database=db_name,
                    user=user,
                    password=password
                )
            else:
                port = port or "3306"
                self.connection = pymysql.connect(
                    host=host,
                    port=int(port),
                    database=db_name,
                    user=user,
                    password=password
                )
                
            self.current_db_type = db_type
            self.logger.info(f"Connected to {db_type} database: {db_name}")
            
            # Save connection details to config
            if not hasattr(self, 'config'):
                self.config = ConfigParser()
                
            if 'Database' not in self.config:
                self.config['Database'] = {}
                
            self.config['Database'].update({
                'type': db_type,
                'host': host,
                'port': port,
                'name': db_name,
                'user': user
            })
            
            self.save_config()
            
        except Exception as e:
            self.connection = None
            self.current_db_type = None
            self.logger.error(f"Failed to connect to database: {str(e)}")
            raise
            
    def create_backup(self, backup_dir=None, backup_format='sql'):
        """Create a database backup"""
        if not self.connection:
            raise Exception("Not connected to a database")
            
        if self.current_db_type == "postgresql" and not self.pg_dump_path:
            raise Exception("pg_dump utility not found")
            
        if self.current_db_type == "mysql" and not self.mysqldump_path:
            raise Exception("mysqldump utility not found")
            
        if not backup_dir:
            backup_dir = self.config.get('Backup', 'location', fallback='.')
            if not backup_dir:
                raise Exception("No backup directory specified")
                
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir)
            except Exception as e:
                raise Exception(f"Cannot create backup directory: {str(e)}")
            
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        db_name = self.config.get('Database', 'name')
        backup_name = f"Backup_{db_name}_{timestamp}"
        
        try:
            if self.current_db_type == "postgresql":
                if backup_format == 'csv':
                    backup_file = self.create_postgres_csv_backup(backup_dir, backup_name)
                else:
                    backup_file = self.create_postgres_sql_backup(backup_dir, backup_name)
            else:
                if backup_format == 'csv':
                    backup_file = self.create_mysql_csv_backup(backup_dir, backup_name)
                else:
                    backup_file = self.create_mysql_sql_backup(backup_dir, backup_name)
                
            self.cleanup_old_backups(backup_dir)
            return backup_file
            
        except Exception as e:
            self.logger.error(f"Backup failed: {str(e)}")
            raise
            
    def create_postgres_sql_backup(self, backup_dir, backup_name):
        """Create PostgreSQL SQL backup"""
        backup_file = os.path.join(backup_dir, f"{backup_name}.sql")
        
        command = [
            self.pg_dump_path,
            "-h", self.config.get('Database', 'host'),
            "-p", self.config.get('Database', 'port', fallback='5432'),
            "-U", self.config.get('Database', 'user'),
            "-f", backup_file,
            self.config.get('Database', 'name')
        ]
        
        env = os.environ.copy()
        env["PGPASSWORD"] = self.config.get('Database', 'password', fallback='')
        
        process = subprocess.Popen(command, env=env, stderr=subprocess.PIPE)
        self.background_processes.append(process)
        _, stderr = process.communicate()
        
        if process.returncode != 0:
            error_msg = self.safe_decode(stderr) if stderr else "Unknown error"
            raise Exception(error_msg)
            
        self.logger.info(f"PostgreSQL backup created: {backup_file}")
        return backup_file
        
    def create_postgres_csv_backup(self, backup_dir, backup_name):
        """Create PostgreSQL CSV backup"""
        csv_dir = os.path.join(backup_dir, backup_name)
        if not os.path.exists(csv_dir):
            os.makedirs(csv_dir)
            
        with self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_type = 'BASE TABLE'
            """)
            tables = cursor.fetchall()
            
            for table in tables:
                table_name = table[0]
                csv_file = os.path.join(csv_dir, f"{table_name}.csv")
                
                with open(csv_file, 'w') as f:
                    cursor.copy_expert(
                        f"COPY {table_name} TO STDOUT WITH CSV HEADER",
                        f
                    )
        
        backup_file = os.path.join(backup_dir, f"{backup_name}.zip")
        shutil.make_archive(
            os.path.join(backup_dir, backup_name),
            'zip',
            csv_dir
        )
        
        shutil.rmtree(csv_dir)
        self.logger.info(f"PostgreSQL CSV backup created: {backup_file}")
        return backup_file
        
    def create_mysql_sql_backup(self, backup_dir, backup_name):
        """Create MySQL SQL backup"""
        backup_file = os.path.join(backup_dir, f"{backup_name}.sql")
        
        command = [
            self.mysqldump_path,
            "-h", self.config.get('Database', 'host'),
            "-P", self.config.get('Database', 'port', fallback='3306'),
            "-u", self.config.get('Database', 'user'),
            f"--password={self.config.get('Database', 'password', fallback='')}",
            self.config.get('Database', 'name')
        ]
        
        with open(backup_file, 'w') as output_file:
            process = subprocess.Popen(command, stdout=output_file, stderr=subprocess.PIPE)
            self.background_processes.append(process)
            _, stderr = process.communicate()
            
            if process.returncode != 0:
                error_msg = self.safe_decode(stderr) if stderr else "Unknown error"
                raise Exception(error_msg)
                
        self.logger.info(f"MySQL backup created: {backup_file}")
        return backup_file
        
    def create_mysql_csv_backup(self, backup_dir, backup_name):
        """Create MySQL CSV backup"""
        csv_dir = os.path.join(backup_dir, backup_name)
        if not os.path.exists(csv_dir):
            os.makedirs(csv_dir)
            
        with self.connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            
            for table in tables:
                table_name = table[0]
                csv_file = os.path.join(csv_dir, f"{table_name}.csv")
                
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                
                cursor.execute(f"SHOW COLUMNS FROM {table_name}")
                columns = [column[0] for column in cursor.fetchall()]
                
                with open(csv_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    writer.writerows(rows)
        
        backup_file = os.path.join(backup_dir, f"{backup_name}.zip")
        shutil.make_archive(
            os.path.join(backup_dir, backup_name),
            'zip',
            csv_dir
        )
        
        shutil.rmtree(csv_dir)
        self.logger.info(f"MySQL CSV backup created: {backup_file}")
        return backup_file
        
    def cleanup_old_backups(self, backup_dir):
        """Clean up old backups, keeping only MAX_BACKUPS most recent"""
        try:
            backups = []
            for filename in os.listdir(backup_dir):
                if filename.startswith("Backup_") and (filename.endswith(".sql") or filename.endswith(".zip")):
                    filepath = os.path.join(backup_dir, filename)
                    mtime = os.path.getmtime(filepath)
                    backups.append((mtime, filepath))
            
            backups.sort()
            
            while len(backups) > MAX_BACKUPS:
                _, oldest_backup = backups.pop(0)
                try:
                    os.remove(oldest_backup)
                    self.logger.info(f"Deleted old backup: {oldest_backup}")
                except Exception as e:
                    self.logger.error(f"Error deleting old backup {oldest_backup}: {str(e)}")
                    
        except Exception as e:
            self.logger.error(f"Error cleaning up old backups: {str(e)}")
            
    def restore_backup(self, backup_file):
        """Restore a database backup"""
        if not self.connection:
            raise Exception("Not connected to a database")
            
        if not os.path.exists(backup_file):
            raise Exception("Backup file does not exist")
            
        try:
            if self.current_db_type == "postgresql":
                if not self.pg_restore_path or not os.path.exists(self.pg_restore_path):
                    raise Exception("pg_restore utility not found")
                    
                if self.connection:
                    self.connection.close()
                    
                command = [
                    self.pg_restore_path,
                    "-h", self.config.get('Database', 'host'),
                    "-p", self.config.get('Database', 'port', fallback='5432'),
                    "-U", self.config.get('Database', 'user'),
                    "-d", self.config.get('Database', 'name'),
                    "-c",
                    backup_file
                ]
                
                env = os.environ.copy()
                env["PGPASSWORD"] = self.config.get('Database', 'password', fallback='')
                
                process = subprocess.Popen(command, env=env, stderr=subprocess.PIPE)
                self.background_processes.append(process)
                _, stderr = process.communicate()
                
                if process.returncode != 0:
                    error_msg = self.safe_decode(stderr) if stderr else "Unknown error"
                    raise Exception(error_msg)
                    
            else:
                if not self.mysql_path or not os.path.exists(self.mysql_path):
                    raise Exception("mysql utility not found")
                    
                if self.connection:
                    self.connection.close()
                    
                command = [
                    self.mysql_path,
                    "-h", self.config.get('Database', 'host'),
                    "-P", self.config.get('Database', 'port', fallback='3306'),
                    "-u", self.config.get('Database', 'user'),
                    f"--password={self.config.get('Database', 'password', fallback='')}",
                    self.config.get('Database', 'name')
                ]
                
                with open(backup_file, 'r') as input_file:
                    process = subprocess.Popen(command, stdin=input_file, stderr=subprocess.PIPE)
                    self.background_processes.append(process)
                    _, stderr = process.communicate()
                    
                    if process.returncode != 0:
                        error_msg = self.safe_decode(stderr) if stderr else "Unknown error"
                        raise Exception(error_msg)
                        
            # Reconnect after restore
            self.connect_to_db(
                self.config.get('Database', 'type'),
                self.config.get('Database', 'host'),
                self.config.get('Database', 'port'),
                self.config.get('Database', 'name'),
                self.config.get('Database', 'user'),
                self.config.get('Database', 'password', fallback='')
            )
            
            self.logger.info(f"Database restored from backup: {backup_file}")
            
        except Exception as e:
            self.logger.error(f"Restore failed: {str(e)}")
            raise
            
    def load_config(self):
        """Load configuration from file"""
        self.config = ConfigParser()
        if os.path.exists(CONFIG_FILE):
            self.config.read(CONFIG_FILE)
            
            # Set up scheduled backup if configured
            schedule = self.config.get('Backup', 'schedule', fallback=None)
            if schedule and schedule != 'disabled':
                self.set_schedule(schedule)
                
        else:
            # Create default config
            self.config['Database'] = {
                'type': 'postgresql',
                'host': 'localhost',
                'port': '',
                'name': '',
                'user': '',
                'password': ''
            }
            
            self.config['Backup'] = {
                'location': '',
                'format': 'sql',
                'schedule': 'disabled'
            }
            
            self.save_config()
            
    def save_config(self):
        """Save configuration to file"""
        with open(CONFIG_FILE, 'w') as configfile:
            self.config.write(configfile)
            
    def start_postgresql_service(self):
        """Start PostgreSQL service (Windows only)"""
        if platform.system() != 'Windows':
            raise Exception("Service control is only available on Windows")
            
        service_name = self.current_postgres_service
        if not service_name:
            raise Exception("PostgreSQL service not detected")
            
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = subprocess.SW_HIDE
            
            proc = subprocess.Popen(
                ['net', 'start', service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=info
            )
            self.background_processes.append(proc)
            proc.wait(timeout=30)
            
            self.logger.info(f"PostgreSQL service started: {service_name}")
            
        except subprocess.TimeoutExpired:
            raise Exception("Service start timed out")
        except Exception as e:
            raise Exception(f"Failed to start PostgreSQL service: {str(e)}")
            
    def stop_postgresql_service(self):
        """Stop PostgreSQL service (Windows only)"""
        if platform.system() != 'Windows':
            raise Exception("Service control is only available on Windows")
            
        service_name = self.current_postgres_service
        if not service_name:
            raise Exception("PostgreSQL service not detected")
            
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = subprocess.SW_HIDE
            
            proc = subprocess.Popen(
                ['net', 'stop', service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=info
            )
            self.background_processes.append(proc)
            proc.wait(timeout=30)
            
            self.logger.info(f"PostgreSQL service stopped: {service_name}")
            
        except subprocess.TimeoutExpired:
            raise Exception("Service stop timed out")
        except Exception as e:
            raise Exception(f"Failed to stop PostgreSQL service: {str(e)}")
            
    def restart_postgresql_service(self):
        """Restart PostgreSQL service (Windows only)"""
        if platform.system() != 'Windows':
            raise Exception("Service control is only available on Windows")
            
        self.stop_postgresql_service()
        time.sleep(2)
        self.start_postgresql_service()
        self.logger.info(f"PostgreSQL service restarted: {self.current_postgres_service}")
        
    def start_mysql_service(self):
        """Start MySQL service (Windows only)"""
        if platform.system() != 'Windows':
            raise Exception("Service control is only available on Windows")
            
        service_name = self.current_mysql_service
        if not service_name:
            raise Exception("MySQL service not detected")
            
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = subprocess.SW_HIDE
            
            proc = subprocess.Popen(
                ['net', 'start', service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=info
            )
            self.background_processes.append(proc)
            proc.wait(timeout=30)
            
            self.logger.info(f"MySQL service started: {service_name}")
            
        except subprocess.TimeoutExpired:
            raise Exception("Service start timed out")
        except Exception as e:
            raise Exception(f"Failed to start MySQL service: {str(e)}")
            
    def stop_mysql_service(self):
        """Stop MySQL service (Windows only)"""
        if platform.system() != 'Windows':
            raise Exception("Service control is only available on Windows")
            
        service_name = self.current_mysql_service
        if not service_name:
            raise Exception("MySQL service not detected")
            
        try:
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = subprocess.SW_HIDE
            
            proc = subprocess.Popen(
                ['net', 'stop', service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=info
            )
            self.background_processes.append(proc)
            proc.wait(timeout=30)
            
            self.logger.info(f"MySQL service stopped: {service_name}")
            
        except subprocess.TimeoutExpired:
            raise Exception("Service stop timed out")
        except Exception as e:
            raise Exception(f"Failed to stop MySQL service: {str(e)}")
            
    def restart_mysql_service(self):
        """Restart MySQL service (Windows only)"""
        if platform.system() != 'Windows':
            raise Exception("Service control is only available on Windows")
            
        self.stop_mysql_service()
        time.sleep(2)
        self.start_mysql_service()
        self.logger.info(f"MySQL service restarted: {self.current_mysql_service}")
        
    def terminate_background_processes(self):
        """Terminate all background processes"""
        for proc in self.background_processes:
            try:
                if isinstance(proc, subprocess.Popen):
                    # Terminate the process tree
                    parent = psutil.Process(proc.pid)
                    for child in parent.children(recursive=True):
                        child.terminate()
                    parent.terminate()
                    
                    # Wait a bit then kill if still running
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        
            except Exception as e:
                self.logger.error(f"Error terminating process {proc}: {str(e)}")
                
        self.background_processes = []
        
    def run(self):
        """Run the service"""
        try:
            self.logger.info("Starting database backup service")
            
            # Start web interface
            self.logger.info(f"Starting web interface on port {WEB_INTERFACE_PORT}")
            self.app.run(host='0.0.0.0', port=WEB_INTERFACE_PORT)
            
        except KeyboardInterrupt:
            self.logger.info("Shutting down gracefully...")
        except Exception as e:
            self.logger.error(f"Service error: {str(e)}")
        finally:
            self.shutdown()
            
    def shutdown(self):
        """Shutdown the service"""
        self.logger.info("Shutting down database backup service")
        
        # Shutdown scheduler
        if hasattr(self, 'scheduler') and self.scheduler:
            self.scheduler.shutdown()
            
        # Close database connection
        if hasattr(self, 'connection') and self.connection:
            self.connection.close()
            
        # Terminate any background processes
        self.terminate_background_processes()
        
        self.logger.info("Service stopped")

if __name__ == "__main__":
    # On Windows, hide the console window if not running in debug mode
    if platform.system() == "Windows" and '--debug' not in sys.argv:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        
    service = DatabaseBackupService()
    service.run()