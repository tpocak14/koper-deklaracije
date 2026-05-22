import cloudinary
import cloudinary.uploader
import cloudinary.api
from flask import current_app
import base64
from datetime import datetime
import uuid

def init_cloudinary():
    """Inicializira Cloudinary konfiguracijo"""
    cloudinary.config(
        cloud_name=current_app.config['CLOUDINARY_CLOUD_NAME'],
        api_key=current_app.config['CLOUDINARY_API_KEY'],
        api_secret=current_app.config['CLOUDINARY_API_SECRET']
    )

def upload_order_image(image_data, order_number, user_id):
    """
    Naloži sliko naročila v Cloudinary
    
    Args:
        image_data: Base64 encoded image data
        order_number: Številka naročila
        user_id: ID uporabnika, ki je naložil sliko
    
    Returns:
        dict: Cloudinary response z URL-jem slike
    """
    try:
        init_cloudinary()
        
        # Ustvari unikatno ime datoteke
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"order_{order_number}_{timestamp}_{unique_id}"
        
        # Naloži sliko v Cloudinary
        result = cloudinary.uploader.upload(
            image_data,
            public_id=f"deklaracije/{filename}",
            folder="order_photos",
            resource_type="image",
            transformation=[
                {"width": 1200, "height": 800, "crop": "limit"},  # Maksimalna velikost
                {"quality": "auto", "fetch_format": "auto"}  # Avtomatska optimizacija
            ]
        )
        
        # Dodaj metadata
        result['order_number'] = order_number
        result['user_id'] = user_id
        result['uploaded_at'] = datetime.now().isoformat()
        
        current_app.logger.info(f"Slika uspešno naložena za naročilo {order_number}: {result['secure_url']}")
        return result
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri nalaganju slike za naročilo {order_number}: {e}")
        raise

def get_order_images(order_number):
    """
    Pridobi vse slike za določeno naročilo
    
    Args:
        order_number: Številka naročila
    
    Returns:
        list: Seznam slik za naročilo
    """
    try:
        init_cloudinary()
        
        # Poišči vse slike v folder-ju za to naročilo
        result = cloudinary.api.resources(
            type="upload",
            prefix=f"order_photos/order_{order_number}_",
            max_results=50
        )
        
        return result.get('resources', [])
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri pridobivanju slik za naročilo {order_number}: {e}")
        return []

def delete_order_image(public_id):
    """
    Izbriši sliko iz Cloudinary
    
    Args:
        public_id: Cloudinary public ID slike
    
    Returns:
        bool: True če je uspešno izbrisana
    """
    try:
        init_cloudinary()
        
        result = cloudinary.uploader.destroy(public_id)
        current_app.logger.info(f"Slika {public_id} uspešno izbrisana")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri brisanju slike {public_id}: {e}")
        return False 