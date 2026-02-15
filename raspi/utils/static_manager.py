"""Static file dependency manager for offline-first operation."""

import os
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# Define dependencies with their download URLs and local paths
DEPENDENCIES = {
    "socket_io": {
        "url": "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.6.1/socket.io.js",
        "local_path": "vendor/js/socket.io.js",
        "description": "Socket.IO client library"
    },
    "font_awesome_css": {
        "url": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
        "local_path": "vendor/css/fontawesome.all.min.css",
        "description": "Font Awesome CSS"
    },
    "font_awesome_webfonts_solid": {
        "url": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-solid-900.woff2",
        "local_path": "vendor/webfonts/fa-solid-900.woff2",
        "description": "Font Awesome Solid WebFont"
    },
    "font_awesome_webfonts_regular": {
        "url": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-regular-400.woff2",
        "local_path": "vendor/webfonts/fa-regular-400.woff2",
        "description": "Font Awesome Regular WebFont"
    },
    "font_awesome_webfonts_brands": {
        "url": "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-brands-400.woff2",
        "local_path": "vendor/webfonts/fa-brands-400.woff2",
        "description": "Font Awesome Brands WebFont"
    },
    "glightbox_css": {
        "url": "https://cdn.jsdelivr.net/npm/glightbox/dist/css/glightbox.min.css",
        "local_path": "vendor/css/glightbox.min.css",
        "description": "GLightbox CSS"
    },
    "glightbox_js": {
        "url": "https://cdn.jsdelivr.net/npm/glightbox/dist/js/glightbox.min.js",
        "local_path": "vendor/js/glightbox.min.js",
        "description": "GLightbox JavaScript"
    },
    "favicon": {
        "url": "https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f916.png",
        "local_path": "favicon.ico",
        "description": "Robot emoji favicon"
    }
}

def get_static_dir():
    """Get the absolute path to the static directory."""
    # Get the directory where this file is located
    utils_dir = Path(__file__).parent.resolve()
    # Go up one level to raspi/, then into static/
    static_dir = utils_dir.parent / "static"
    return static_dir

def download_file(url: str, local_path: Path, description: str) -> bool:
    """Download a file from URL to local path."""
    try:
        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Download the file
        logger.info(f"Downloading {description} from {url}")
        urllib.request.urlretrieve(url, local_path)
        
        # Verify file was downloaded and has content
        if local_path.exists() and local_path.stat().st_size > 0:
            logger.info(f"✓ {description} downloaded successfully ({local_path.stat().st_size} bytes)")
            return True
        else:
            logger.error(f"✗ {description} download failed - file is empty")
            return False
            
    except Exception as e:
        logger.error(f"✗ Failed to download {description}: {e}")
        return False

def ensure_static_files(force_download: bool = False) -> dict:
    """
    Ensure all static dependencies are available locally.
    
    Args:
        force_download: If True, re-download even if files exist
        
    Returns:
        dict with status of each dependency
    """
    static_dir = get_static_dir()
    results = {}
    
    logger.info("Checking static dependencies...")
    
    for key, dep in DEPENDENCIES.items():
        local_path = static_dir / dep["local_path"]
        
        # Check if file already exists
        if not force_download and local_path.exists():
            file_size = local_path.stat().st_size
            logger.debug(f"✓ {dep['description']} already exists ({file_size} bytes)")
            results[key] = {
                "success": True,
                "path": str(local_path),
                "downloaded": False,
                "size": file_size
            }
        else:
            # Download the file
            success = download_file(dep["url"], local_path, dep["description"])
            results[key] = {
                "success": success,
                "path": str(local_path) if success else None,
                "downloaded": success,
                "size": local_path.stat().st_size if success else 0
            }
    
    # Summary
    total = len(results)
    successful = sum(1 for r in results.values() if r["success"])
    downloaded = sum(1 for r in results.values() if r.get("downloaded"))
    existing = successful - downloaded
    
    logger.info(f"Static files: {successful}/{total} ready ({downloaded} downloaded, {existing} cached)")
    
    return results

def get_vendor_path(filename: str) -> str:
    """
    Get the URL path for a vendor file to use in templates.
    
    Args:
        filename: The filename (e.g., 'socket.io.js')
        
    Returns:
        URL path string for use with url_for()
    """
    # Map common filenames to their paths
    path_map = {
        "socket.io.js": "vendor/js/socket.io.js",
        "fontawesome.all.min.css": "vendor/css/fontawesome.all.min.css",
        "glightbox.min.css": "vendor/css/glightbox.min.css",
        "glightbox.min.js": "vendor/js/glightbox.min.js",
        "favicon.ico": "favicon.ico"
    }
    
    return path_map.get(filename, f"vendor/{filename}")

if __name__ == "__main__":
    # Can be run standalone to pre-download files
    logging.basicConfig(level=logging.INFO)
    ensure_static_files()
