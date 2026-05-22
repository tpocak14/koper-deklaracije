import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.config import Config
from flask import current_app
import base64
from datetime import datetime
import uuid
from PIL import Image
import io
import os
import traceback

def get_s3_client():
    """Vrne S3 client z konfiguracijo"""
    try:
        region = current_app.config['AWS_REGION']
        # Uporabi virtual-hosted-style URL (bucket.s3.region.amazonaws.com) za presigned URL-je,
        # ker path-style (s3.region.amazonaws.com/bucket/...) ni podprt v vseh regijah.
        return boto3.client(
            's3',
            aws_access_key_id=current_app.config['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=current_app.config['AWS_SECRET_ACCESS_KEY'],
            region_name=region,
            config=Config(s3={'addressing_style': 'virtual'})
        )
    except Exception as e:
        current_app.logger.error(f"Napaka pri inicializaciji S3 client: {e}")
        raise

def upload_order_image_bytes(file_bytes, order_number, user_id, content_type='image/jpeg', skip_processing=False):
    """
    Naloži sliko naročila v S3 iz binarnih podatkov.
    """
    try:
        s3_client = get_s3_client()
        bucket_name = current_app.config['S3_BUCKET_NAME']

        # Ustvari unikatno ime datoteke
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"order_{order_number}_{timestamp}_{unique_id}.jpg"
        s3_key = f"order_photos/{filename}"

        if skip_processing:
            output_buffer = io.BytesIO(file_bytes)
        else:
            # Optimiziraj sliko z Pillow
            with Image.open(io.BytesIO(file_bytes)) as img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                max_size = (1200, 800)
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                output_buffer = io.BytesIO()
                # Optimizacija lahko precej upočasni, zato je privzeto izklopljena
                img.save(output_buffer, format='JPEG', quality=82, optimize=False)
                output_buffer.seek(0)

        s3_client.upload_fileobj(
            output_buffer,
            bucket_name,
            s3_key,
            ExtraArgs={
                'ContentType': content_type or 'image/jpeg',
                'Metadata': {
                    'order_number': order_number,
                    'user_id': user_id,
                    'uploaded_at': datetime.now().isoformat()
                }
            }
        )

        image_url = generate_presigned_url(s3_key, expiration=3600*24*7, operation='get_object')
        current_app.logger.info(f"Generated presigned URL for {s3_key}: {image_url[:100]}...")

        result = {
            'public_id': s3_key,
            'secure_url': image_url,
            'order_number': order_number,
            'user_id': user_id,
            'uploaded_at': datetime.now().isoformat()
        }

        current_app.logger.info(f"Slika uspešno naložena v S3 za naročilo {order_number}: {image_url}")
        return result
    except Exception as e:
        current_app.logger.error(f"Napaka pri nalaganju slike v S3 za naročilo {order_number}: {e}")
        current_app.logger.error(f"Stack trace: {traceback.format_exc()}")
        raise

def upload_order_image(image_data, order_number, user_id):
    """
    Naloži sliko naročila v S3
    
    Args:
        image_data: Base64 encoded image data
        order_number: Številka naročila
        user_id: ID uporabnika, ki je naložil sliko
    
    Returns:
        dict: S3 response z URL-jem slike
    """
    try:
        if image_data.startswith('data:image'):
            image_data = image_data.split(',')[1]
        image_bytes = base64.b64decode(image_data)
        return upload_order_image_bytes(
            image_bytes,
            order_number,
            user_id,
            content_type='image/jpeg',
            skip_processing=False
        )
    except Exception as e:
        current_app.logger.error(f"Napaka pri nalaganju slike v S3 za naročilo {order_number}: {e}")
        current_app.logger.error(f"Stack trace: {traceback.format_exc()}")
        raise

def generate_presigned_post_for_order_image(s3_key, content_type, max_size_bytes, expiration=600):
    """Ustvari presigned POST za direkten upload slike v S3."""
    s3_client = get_s3_client()
    bucket_name = current_app.config['S3_BUCKET_NAME']
    fields = {
        'Content-Type': content_type,
        'key': s3_key,
    }
    conditions = [
        {'Content-Type': content_type},
        {'key': s3_key},
        ['content-length-range', 1, max_size_bytes],
    ]
    return s3_client.generate_presigned_post(
        bucket_name,
        s3_key,
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=expiration,
    )

def upload_returned_damaged_image(file_storage, order_number, package_type, user_id):
    """Naloži sliko za vrnjene/poškodovane pakete v S3 v ustrezno mapo.
    
    Args:
        file_storage: werkzeug.datastructures.FileStorage (request.files['image'])
        order_number: Številka naročila
        package_type: 'returned' ali 'damaged'
        user_id: ID uporabnika, ki nalaga sliko
    
    Returns:
        dict: {'key': s3_key, 'url': public_url}
    """
    try:
        # Preveri konfiguracijo
        bucket_name = current_app.config.get('S3_BUCKET_NAME')
        if not bucket_name:
            raise RuntimeError('S3_BUCKET_NAME ni nastavljen')
        
        # Validiraj package_type
        if package_type not in ('returned', 'damaged'):
            raise ValueError('package_type mora biti "returned" ali "damaged"')
        
        s3_client = get_s3_client()
        
        # Preberi binarne podatke in optimiziraj
        file_storage.stream.seek(0)
        file_bytes = file_storage.read()
        filename_orig = file_storage.filename or 'image'
        
        with Image.open(io.BytesIO(file_bytes)) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            max_size = (1200, 800)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=85, optimize=True)
            output_buffer.seek(0)
        
        # Ustvari S3 key z ustrezno mapo glede na tip
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"order_{order_number}_{timestamp}_{unique_id}.jpg"
        
        # Ločene mape za vrnjene in poškodovane pakete
        if package_type == 'returned':
            s3_key = f"returned_packages/{filename}"
        else:  # damaged
            s3_key = f"damaged_packages/{filename}"
        
        # Naloži v S3
        s3_client.upload_fileobj(
            output_buffer,
            bucket_name,
            s3_key,
            ExtraArgs={
                'ContentType': 'image/jpeg',
                'Metadata': {
                    'order_number': str(order_number),
                    'package_type': package_type,
                    'user_id': str(user_id),
                    'uploaded_at': datetime.now().isoformat()
                }
            }
        )
        
        # Ustvari presigned URL
        url = generate_presigned_url(s3_key, expiration=3600*24*7, operation='get_object')  # 7 dni
        
        current_app.logger.info(f"Slika za {package_type} paket (naročilo {order_number}) uspešno naložena: {s3_key}")
        return {'key': s3_key, 'url': url}
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri nalaganju slike za {package_type} paket: {e}")
        current_app.logger.error(f"Stack: {traceback.format_exc()}")
        raise

def upload_instruction_image(file_storage, user_id):
    """Naloži sliko za navodila v S3 in vrne javni URL.

    Args:
        file_storage: werkzeug.datastructures.FileStorage (request.files['image'])
        user_id: ID uporabnika, ki nalaga sliko
    """
    try:
        # Preveri konfiguracijo
        bucket_name = current_app.config.get('S3_BUCKET_NAME')
        if not bucket_name:
            raise RuntimeError('S3_BUCKET_NAME ni nastavljen')
        _ = current_app.config.get('AWS_ACCESS_KEY_ID')
        _ = current_app.config.get('AWS_SECRET_ACCESS_KEY')

        s3_client = get_s3_client()

        # Preberi binarne podatke in optimiziraj (če je slika)
        file_storage.stream.seek(0)
        file_bytes = file_storage.read()
        filename_orig = file_storage.filename or 'image'
        ext = os.path.splitext(filename_orig)[1].lower() or '.jpg'

        with Image.open(io.BytesIO(file_bytes)) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            max_size = (1400, 1200)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=85, optimize=True)
            output_buffer.seek(0)

        key = f"instruction_images/{uuid.uuid4().hex}.jpg"
        s3_client.upload_fileobj(
            output_buffer,
            bucket_name,
            key,
            ExtraArgs={
                'ContentType': 'image/jpeg',
                'Metadata': {
                    'user_id': str(user_id),
                    'uploaded_at': datetime.now().isoformat()
                }
            }
        )

        url = generate_presigned_url(key, expiration=3600*24*7, operation='get_object')  # 7 dni
        return {'key': key, 'url': url}
    except Exception as e:
        current_app.logger.error(f"Napaka pri nalaganju slike navodil: {e}")
        current_app.logger.error(f"Stack: {traceback.format_exc()}")
        raise

def get_order_images(order_number):
    """
    Pridobi vse slike za določeno naročilo iz S3
    
    Args:
        order_number: Številka naročila
    
    Returns:
        list: Seznam slik za naročilo
    """
    try:
        s3_client = get_s3_client()
        bucket_name = current_app.config['S3_BUCKET_NAME']
        
        # Poišči vse objekte z prefix-om za to naročilo
        prefix = f"order_photos/order_{order_number}_"
        
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=prefix,
            MaxKeys=50
        )
        
        images = []
        if 'Contents' in response:
            for obj in response['Contents']:
                s3_key = obj['Key']
                
                # Ustvari presigned URL
                image_url = generate_presigned_url(s3_key, expiration=3600*24*7, operation='get_object')  # 7 dni
                current_app.logger.info(f"Generated presigned URL for {s3_key}: {image_url[:100]}...")
                
                # Pridobi metadata
                try:
                    metadata_response = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                    metadata = metadata_response.get('Metadata', {})
                except:
                    metadata = {}
                
                images.append({
                    'public_id': s3_key,
                    'secure_url': image_url,
                    'order_number': metadata.get('order_number', order_number),
                    'user_id': metadata.get('user_id', 'unknown'),
                    'uploaded_at': metadata.get('uploaded_at', obj['LastModified'].isoformat()),
                    'size': obj['Size']
                })
        
        return images
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri pridobivanju slik iz S3 za naročilo {order_number}: {e}")
        return []

def get_returned_damaged_images(order_number=None, package_type=None):
    """
    Pridobi slike za vrnjene/poškodovane pakete iz S3
    
    Args:
        order_number: Številka naročila (opcijsko - če podano, filtrira po naročilu)
        package_type: 'returned' ali 'damaged' (opcijsko - če podano, filtrira po tipu)
    
    Returns:
        list: Seznam slik
    """
    try:
        s3_client = get_s3_client()
        bucket_name = current_app.config['S3_BUCKET_NAME']
        
        images = []
        
        # Določi prefixe za iskanje
        prefixes = []
        if package_type == 'returned':
            prefixes = ['returned_packages/']
        elif package_type == 'damaged':
            prefixes = ['damaged_packages/']
        else:
            # Če tip ni podan, išči v obeh mapah
            prefixes = ['returned_packages/', 'damaged_packages/']
        
        for prefix in prefixes:
            if order_number:
                # Filtriranje po naročilu
                search_prefix = f"{prefix}order_{order_number}_"
            else:
                # Vse slike v mapi
                search_prefix = prefix
            
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=search_prefix,
                MaxKeys=100
            )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    s3_key = obj['Key']
                    
                    # Ustvari URL - uporabi proxy da se izognemo CORS problemom
                    if current_app.config.get('CLOUDFRONT_DOMAIN'):
                        image_url = f"https://{current_app.config['CLOUDFRONT_DOMAIN']}/{s3_key}"
                    else:
                        # Uporabi naš proxy endpoint namesto presigned URL-ja
                        from flask import url_for
                        image_url = url_for('api.proxy_returned_damaged_image', s3_key=s3_key, _external=True)
                    
                    # Pridobi metadata
                    try:
                        metadata_response = s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                        metadata = metadata_response.get('Metadata', {})
                    except:
                        metadata = {}
                    
                    # Določi tip iz poti če ni v metadatah
                    detected_type = 'returned' if s3_key.startswith('returned_packages/') else 'damaged'
                    
                    images.append({
                        'public_id': s3_key,
                        'secure_url': image_url,
                        'order_number': metadata.get('order_number', 'unknown'),
                        'package_type': metadata.get('package_type', detected_type),
                        'user_id': metadata.get('user_id', 'unknown'),
                        'uploaded_at': metadata.get('uploaded_at', obj['LastModified'].isoformat()),
                        'size': obj['Size']
                    })
        
        return images
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri pridobivanju returned/damaged slik iz S3: {e}")
        return []

def delete_order_image(public_id):
    """
    Izbriši sliko iz S3
    
    Args:
        public_id: S3 key slike
    
    Returns:
        bool: True če je uspešno izbrisana
    """
    try:
        s3_client = get_s3_client()
        bucket_name = current_app.config['S3_BUCKET_NAME']
        
        s3_client.delete_object(Bucket=bucket_name, Key=public_id)
        current_app.logger.info(f"Slika {public_id} uspešno izbrisana iz S3")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri brisanju slike {public_id} iz S3: {e}")
        return False

def generate_presigned_url(s3_key, expiration=3600, operation='get_object'):
    """
    Ustvari presigned URL za varno dostopanje do objektov
    
    Args:
        s3_key: S3 key za objekt
        expiration: Čas poteka URL-ja v sekundah
        operation: Operacija ('get_object' za branje, 'put_object' za pisanje)
    
    Returns:
        str: Presigned URL ali CloudFront URL
    """
    try:
        # Če je CloudFront nastavljen, uporabi CloudFront URL
        if current_app.config.get('CLOUDFRONT_DOMAIN'):
            cloudfront_url = f"https://{current_app.config['CLOUDFRONT_DOMAIN']}/{s3_key}"
            current_app.logger.info(f"Using CloudFront URL: {cloudfront_url}")
            return cloudfront_url
        
        # Sicer generiraj presigned URL z virtual-hosted-style
        s3_client = get_s3_client()
        bucket_name = current_app.config['S3_BUCKET_NAME']

        current_app.logger.info(f"Generating presigned URL for {s3_key} with operation {operation}")
        current_app.logger.info(f"Bucket: {bucket_name}, Expiration: {expiration} seconds")

        url = s3_client.generate_presigned_url(
            ClientMethod=operation,
            Params={'Bucket': bucket_name, 'Key': s3_key},
            ExpiresIn=expiration
        )
        
        current_app.logger.info(f"Generated presigned URL: {url[:100]}...")
        
        return url
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri generiranju presigned URL: {e}")
        current_app.logger.error(f"Stack trace: {traceback.format_exc()}")
        return None

def setup_s3_cors():
    """
    Nastavi CORS konfiguracijo za S3 bucket
    
    Returns:
        bool: True če je uspešno nastavljena
    """
    try:
        s3_client = get_s3_client()
        bucket_name = current_app.config['S3_BUCKET_NAME']
        
        cors_configuration = {
            'CORSRules': [
                {
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'HEAD', 'PUT', 'POST'],
                    'AllowedOrigins': [
                        'https://deklaracije.eu',
                        'https://amour-deklaracije-staging-b471d76b507e.herokuapp.com',
                        'http://localhost:5000',
                        'http://127.0.0.1:5000'
                    ],
                    # AWS S3 ne podpira wildcard v ExposeHeaders, zato naštejemo eksplicitne
                    'ExposeHeaders': ['ETag', 'x-amz-meta-order_number', 'x-amz-meta-user_id', 'x-amz-meta-uploaded_at', 'x-amz-request-id'],
                    'MaxAgeSeconds': 3600
                },
                {
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'HEAD'],
                    'AllowedOrigins': ['*'],
                    'ExposeHeaders': ['ETag'],
                    'MaxAgeSeconds': 3600
                }
            ]
        }
        
        s3_client.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration=cors_configuration
        )
        
        current_app.logger.info(f"CORS konfiguracija uspešno nastavljena za bucket {bucket_name}")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri nastavljanju CORS konfiguracije: {e}")
        return False 


def upload_purchase_order_image(file_bytes: bytes, purchase_order_id: int, user_id: int | str):
    """Naloži sliko prejemnice za purchase order v S3 (po_receipts/...).

    Args:
        file_bytes: surovi bajti slike
        purchase_order_id: ID naročila robe
        user_id: ID ali username uporabnika

    Returns:
        dict: {'key': s3_key, 'url': proxy_or_presigned_url}
    """
    try:
        # Optimiziraj sliko (kot drugje)
        with Image.open(io.BytesIO(file_bytes)) as img:
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            max_size = (1400, 1200)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            output_buffer = io.BytesIO()
            img.save(output_buffer, format='JPEG', quality=85, optimize=True)
            output_buffer.seek(0)

        s3_client = get_s3_client()
        bucket_name = current_app.config['S3_BUCKET_NAME']

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        filename = f"po_{purchase_order_id}_{timestamp}_{unique_id}.jpg"
        s3_key = f"po_receipts/{filename}"

        s3_client.upload_fileobj(
            output_buffer,
            bucket_name,
            s3_key,
            ExtraArgs={
                'ContentType': 'image/jpeg',
                'Metadata': {
                    'purchase_order_id': str(purchase_order_id),
                    'user_id': str(user_id),
                    'uploaded_at': datetime.now().isoformat()
                }
            }
        )

        # Vrni presigned URL ali CloudFront
        url = generate_presigned_url(s3_key, expiration=3600*24*7, operation='get_object')
        return {'key': s3_key, 'url': url}
    except Exception as e:
        current_app.logger.error(f"Napaka pri nalaganju PO slike v S3: {e}")
        current_app.logger.error(f"Stack: {traceback.format_exc()}")
        raise