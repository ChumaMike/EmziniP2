import os
from app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    socketio.run(app, debug=debug, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
