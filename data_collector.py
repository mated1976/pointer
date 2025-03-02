import requests
import json
import time
from flask import request
import threading

class DataCollector:
    def __init__(self, endpoint_urls=None):
        self.endpoint_urls = endpoint_urls or []
        self.queue = []
        self.lock = threading.Lock()
        
    def add_endpoint(self, url):
        """Add a new endpoint to send data to"""
        if url not in self.endpoint_urls:
            self.endpoint_urls.append(url)
    
    def log_usage(self, event_type, details=None):
        """Log a usage event with the current timestamp and user info"""
        if not self.endpoint_urls:
            return  # Skip if no endpoints configured
            
        # Get user info
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', 'Unknown')
        
        # Create event data
        event_data = {
            'timestamp': int(time.time()),
            'event': event_type,
            'ip': ip,
            'user_agent': user_agent,
            'details': details or {}
        }
        
        # Add to queue for async sending
        with self.lock:
            self.queue.append(event_data)
        
        # Start a thread to send the data
        threading.Thread(target=self._send_data).start()
    
    def _send_data(self):
        """Send queued data to all endpoints"""
        if not self.queue:
            return
            
        # Get data from queue
        with self.lock:
            data_to_send = self.queue.copy()
            self.queue = []
        
        # Try to send to each endpoint
        for endpoint in self.endpoint_urls:
            try:
                requests.post(
                    endpoint,
                    json={'events': data_to_send},
                    headers={'Content-Type': 'application/json'},
                    timeout=5
                )
            except Exception as e:
                print(f"Error sending data to {endpoint}: {e}")