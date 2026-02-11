# Configuration Settings

chunk_size = 4096  # Size of chunks to be processed
overlap = 512      # Overlap between chunks

# Password requirements
password_requirements = {
    'min_length': 8,
    'upper_case': True,
    'lower_case': True,
    'numbers': True,
    'special_characters': True
}

# Logging setup
logging_config = {
    'level': 'INFO',
    'format': '%(asctime)s - %(levelname)s - %(message)s',
    'filename': 'app.log'
}
