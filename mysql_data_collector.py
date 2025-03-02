import time
import json
import threading
from flask import request
import mysql.connector
from mysql.connector import pooling

class MySQLDataCollector:
    def __init__(self, db_config):
        """
        Initialize the MySQL data collector with database configuration
        
        db_config should be a dict with:
        {
            'host': 'your_host',
            'database': 'your_database',
            'user': 'your_username',
            'password': 'your_password',
            'port': 3306  # Default MySQL port
        }
        """
        self.db_config = db_config
        self.queue = []
        self.lock = threading.Lock()
        
        # Create connection pool
        self.cnx_pool = mysql.connector.pooling.MySQLConnectionPool(
            pool_name="pointing_app_pool",
            pool_size=5,
            **db_config
        )
        
        # Check if table exists but don't try to create it
        self._init_database()
    
    def _init_database(self):
        """Check if table exists but don't try to create it"""
        try:
            cnx = self.cnx_pool.get_connection()
            cursor = cnx.cursor()
            
            # Just check if table exists
            cursor.execute("SHOW TABLES LIKE 'app_events'")
            table_exists = cursor.fetchone() is not None
            
            cursor.close()
            cnx.close()
            
            if not table_exists:
                print("WARNING: Table 'app_events' does not exist.")
                print("Please make sure the table is created with the correct structure.")
        except Exception as e:
            print(f"Error checking database: {e}")
    
    def log_usage(self, event_type, details=None):
        """Log a usage event with the current timestamp and user info"""
        # Get user info
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        # Create event data
        event_data = {
            'timestamp': int(time.time()),
            'event_type': event_type,
            'ip': ip,
            'user_agent': user_agent,
            'details': json.dumps(details or {})
        }
        
        # Add to queue for async processing
        with self.lock:
            self.queue.append(event_data)
        
        # Start a thread to process the queue
        threading.Thread(target=self._process_queue).start()
    
    def _process_queue(self):
        """Process queued events and insert into database"""
        if not self.queue:
            return
        
        # Get events from queue
        with self.lock:
            events_to_process = self.queue.copy()
            self.queue = []
        
        try:
            # Get connection from pool
            cnx = self.cnx_pool.get_connection()
            cursor = cnx.cursor()
            
            # Insert events
            for event in events_to_process:
                cursor.execute("""
                    INSERT INTO app_events 
                    (timestamp, event_type, ip, user_agent, details)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    event['timestamp'],
                    event['event_type'],
                    event['ip'],
                    event['user_agent'],
                    event['details']
                ))
            
            # Commit and clean up
            cnx.commit()
            cursor.close()
            cnx.close()
        except Exception as e:
            print(f"Error inserting events into database: {e}")
            # If we failed to insert, put events back in queue
            with self.lock:
                self.queue.extend(events_to_process)
    
    def get_stats(self, days=7):
        """Get usage statistics for the past X days"""
        try:
            # Get connection from pool
            cnx = self.cnx_pool.get_connection()
            cursor = cnx.cursor(dictionary=True)
            
            # Calculate timestamp for X days ago
            cutoff_time = int(time.time()) - (days * 86400)
            
            # Get event counts by type
            cursor.execute("""
                SELECT event_type, COUNT(*) as count
                FROM app_events
                WHERE timestamp > %s
                GROUP BY event_type
            """, (cutoff_time,))
            
            event_counts = cursor.fetchall()
            
            # Get unique IPs (users)
            cursor.execute("""
                SELECT COUNT(DISTINCT ip) as unique_users
                FROM app_events
                WHERE timestamp > %s
            """, (cutoff_time,))
            
            unique_users = cursor.fetchone()['unique_users']
            
            # Clean up
            cursor.close()
            cnx.close()
            
            return {
                'event_counts': event_counts,
                'unique_users': unique_users,
                'period_days': days
            }
        except Exception as e:
            print(f"Error fetching stats: {e}")
            return {'error': str(e)}