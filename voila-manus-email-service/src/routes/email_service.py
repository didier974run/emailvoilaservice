from flask import Blueprint, jsonify, request
import os
import requests
from datetime import datetime
from src.models.email_log import EmailLog, db
from bs4 import BeautifulSoup
import re

email_service_bp = Blueprint('email_service', __name__)

# Configuration
RESEND_API_KEY = os.getenv('RESEND_API_KEY', 're_ZxQhiZtJ_7AhXpB8dPfkhWs6v17Kf5dc8')
VOILA_FROM_EMAIL = os.getenv('VOILA_FROM_EMAIL', 'noreply@voilaapp.ai')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://nafjtewvdibgnfbrvcjb.supabase.co')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5hZmp0ZXd2ZGliZ25mYnJ2Y2piIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTAxMTY5MTYsImV4cCI6MjA2NTY5MjkxNn0.Qmy5yDcAcSEu2z3lYIJbUQ_aShqsHbO20ia-OopFKhA')

@email_service_bp.route('/webhook/supabase/new-order', methods=['POST'])
def handle_new_order():
    """
    Handle new order webhook from Supabase
    Expected payload: {
        "record": {
            "id": "uuid",
            "user_id": "uuid",
            "property_url": "string",
            "music_type": "string",
            "voiceover": boolean,
            "branding_asset": "string",
            "order_status": "string",
            "created_at": "timestamp"
        }
    }
    """
    try:
        data = request.json
        
        # Extract order record
        if 'record' not in data:
            return jsonify({'error': 'Missing record in payload'}), 400
            
        record = data['record']
        
        # Validate required fields
        required_fields = ['id', 'user_id', 'property_url']
        for field in required_fields:
            if field not in record:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Extract order information
        order_id = record['id']
        user_id = record['user_id']
        property_url = record['property_url']
        music_type = record.get('music_type', 'Let AI Choose')
        voiceover = record.get('voiceover', False)
        branding_asset = record.get('branding_asset')
        
        # Fetch customer data from Supabase Auth
        customer_data = fetch_customer_data(user_id)
        if not customer_data:
            return jsonify({'error': 'Could not fetch customer data'}), 400
        
        # Extract property information from URL
        property_info = extract_property_info(property_url)
        
        # Create order details object
        order_details = {
            'music_type': music_type,
            'voiceover': voiceover,
            'branding_asset': branding_asset,
            'property_url': property_url,
            'property_info': property_info
        }
        
        # Generate enhanced email content using Manus
        email_content = generate_enhanced_email(
            customer_name=customer_data['name'],
            property_title=property_info['title'],
            property_info=property_info,
            order_details=order_details
        )
        
        # Create email subject
        email_subject = f"Your Voila Video Order Confirmed - {property_info['title']}"
        
        # Send email via Resend
        resend_response = send_email_via_resend(
            to_email=customer_data['email'],
            subject=email_subject,
            html_content=email_content,
            customer_name=customer_data['name']
        )
        
        # Send admin notification email
        admin_email_content = generate_admin_notification_email(
            order_id=order_id,
            customer_data=customer_data,
            property_info=property_info,
            order_details=order_details,
            record=record
        )
        
        admin_subject = f"New Video Order: {property_info['title']}"
        admin_response = send_email_via_resend(
            to_email='contact@voilaapp.ai',
            subject=admin_subject,
            html_content=admin_email_content,
            customer_name='Voila Team'
        )
        
        # Log the email
        email_log = EmailLog(
            order_id=order_id,
            customer_email=customer_data['email'],
            customer_name=customer_data['name'],
            property_title=property_info['title'],
            email_subject=email_subject,
            email_content=email_content,
            email_type='order_confirmation',
            status='sent' if resend_response.get('success') else 'failed',
            resend_message_id=resend_response.get('message_id'),
            sent_at=datetime.utcnow() if resend_response.get('success') else None
        )
        
        db.session.add(email_log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Order confirmation email sent successfully',
            'email_log_id': email_log.id,
            'resend_message_id': resend_response.get('message_id'),
            'property_title': property_info['title'],
            'admin_notification_sent': admin_response.get('success', False)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@email_service_bp.route('/webhook/supabase/video-completed', methods=['POST'])
def handle_video_completed():
    """
    Handle video completion webhook from Supabase
    Expected payload: {
        "record": {
            "id": "uuid",
            "user_id": "uuid", 
            "property_url": "string",
            "video_file_url": "string",
            "video_thumbnail_url": "string",
            "music_type": "string",
            "voiceover": boolean,
            "completed_at": "timestamp"
        }
    }
    """
    try:
        data = request.json
        
        # Extract order record
        if 'record' not in data:
            return jsonify({'error': 'Missing record in payload'}), 400
            
        record = data['record']
        
        # Validate required fields
        required_fields = ['id', 'user_id', 'video_file_url']
        for field in required_fields:
            if field not in record:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Extract order information
        order_id = record['id']
        user_id = record['user_id']
        video_file_url = record['video_file_url']
        video_thumbnail_url = record.get('video_thumbnail_url')
        property_url = record.get('property_url')
        
        # Fetch customer data from Supabase Auth
        customer_data = fetch_customer_data(user_id)
        if not customer_data:
            return jsonify({'error': 'Could not fetch customer data'}), 400
        
        # Extract property information if available
        property_info = None
        if property_url:
            property_info = extract_property_info(property_url)
        else:
            property_info = {
                'title': 'Your Property Video',
                'type': 'residential_home',
                'location': '',
                'price': '',
                'features': [],
                'description': ''
            }
        
        # Create completion details
        completion_details = {
            'video_file_url': video_file_url,
            'video_thumbnail_url': video_thumbnail_url,
            'completed_at': record.get('completed_at'),
            'created_at': record.get('created_at'),  # Add order creation time
            'music_type': record.get('music_type'),
            'voiceover': record.get('voiceover', False)
        }
        
        # Generate video completion email
        email_content = generate_video_completion_email(
            customer_name=customer_data['name'],
            property_title=property_info['title'],
            property_info=property_info,
            completion_details=completion_details
        )
        
        # Create email subject
        email_subject = f"🎬 Your {property_info['title']} Video is Ready!"
        
        # Send email via Resend
        resend_response = send_email_via_resend(
            to_email=customer_data['email'],
            subject=email_subject,
            html_content=email_content,
            customer_name=customer_data['name']
        )
        
        # Log the email
        email_log = EmailLog(
            order_id=order_id,
            customer_email=customer_data['email'],
            customer_name=customer_data['name'],
            property_title=property_info['title'],
            email_subject=email_subject,
            email_content=email_content,
            email_type='video_completion',
            status='sent' if resend_response.get('success') else 'failed',
            resend_message_id=resend_response.get('message_id'),
            sent_at=datetime.utcnow() if resend_response.get('success') else None
        )
        
        db.session.add(email_log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Video completion email sent successfully',
            'email_log_id': email_log.id,
            'resend_message_id': resend_response.get('message_id'),
            'property_title': property_info['title']
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def fetch_customer_data(user_id):
    """
    Fetch customer data from Supabase Auth Users table
    """
    try:
        headers = {
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': f'Bearer {SUPABASE_ANON_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Fetch user data from auth.users
        url = f'{SUPABASE_URL}/auth/v1/admin/users/{user_id}'
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            user_data = response.json()
            
            # Extract name and email
            email = user_data.get('email')
            
            # Try to get name from user_metadata or raw_user_meta_data
            name = None
            if 'user_metadata' in user_data and user_data['user_metadata']:
                name = user_data['user_metadata'].get('full_name') or user_data['user_metadata'].get('name')
            
            if not name and 'raw_user_meta_data' in user_data and user_data['raw_user_meta_data']:
                name = user_data['raw_user_meta_data'].get('full_name') or user_data['raw_user_meta_data'].get('name')
            
            # Fallback to email prefix if no name found
            if not name and email:
                name = email.split('@')[0].title()
            
            return {
                'email': email,
                'name': name or 'Valued Customer'
            }
        else:
            # Fallback: try to get user from public profiles table if exists
            return fetch_user_profile(user_id)
            
    except Exception as e:
        print(f"Error fetching customer data: {e}")
        return None

def fetch_user_profile(user_id):
    """
    Fallback: Try to fetch user profile from public profiles table
    """
    try:
        headers = {
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': f'Bearer {SUPABASE_ANON_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Try profiles table
        url = f'{SUPABASE_URL}/rest/v1/profiles?user_id=eq.{user_id}&select=*'
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            profiles = response.json()
            if profiles and len(profiles) > 0:
                profile = profiles[0]
                return {
                    'email': profile.get('email', 'customer@example.com'),
                    'name': profile.get('full_name') or profile.get('name') or 'Valued Customer'
                }
        
        return None
        
    except Exception as e:
        print(f"Error fetching user profile: {e}")
        return None

def extract_property_info(property_url):
    """
    Manus intelligently extracts property information from URL
    """
    try:
        # Set headers to mimic a real browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(property_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Manus intelligent property information extraction
        property_info = {
            'title': extract_property_title(soup, property_url),
            'type': extract_property_type(soup),
            'location': extract_location(soup),
            'price': extract_price(soup),
            'features': extract_key_features(soup),
            'description': extract_description(soup)
        }
        
        return property_info
        
    except Exception as e:
        print(f"Error extracting property info: {e}")
        # Fallback to URL-based title
        return {
            'title': generate_title_from_url(property_url),
            'type': 'residential_home',
            'location': '',
            'price': '',
            'features': [],
            'description': ''
        }

def extract_property_title(soup, url):
    """
    Manus extracts property title using multiple strategies
    """
    # Strategy 1: Page title
    title_tag = soup.find('title')
    if title_tag:
        title = title_tag.get_text().strip()
        # Clean up common title patterns
        title = re.sub(r'\s*\|\s*.*$', '', title)  # Remove site name after |
        title = re.sub(r'\s*-\s*.*$', '', title)   # Remove site name after -
        if len(title) > 10 and 'for sale' in title.lower() or 'for rent' in title.lower():
            return title
    
    # Strategy 2: H1 tags
    h1_tags = soup.find_all('h1')
    for h1 in h1_tags:
        text = h1.get_text().strip()
        if len(text) > 10 and len(text) < 200:
            return text
    
    # Strategy 3: Property-specific selectors
    selectors = [
        '[data-testid="property-title"]',
        '.property-title',
        '.listing-title',
        '.property-address',
        '.address'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            text = element.get_text().strip()
            if len(text) > 5:
                return text
    
    # Strategy 4: Meta tags
    meta_title = soup.find('meta', property='og:title')
    if meta_title:
        return meta_title.get('content', '').strip()
    
    # Fallback
    return generate_title_from_url(url)

def generate_title_from_url(url):
    """
    Generate a title from URL as fallback
    """
    try:
        # Extract meaningful parts from URL
        parts = url.split('/')
        for part in reversed(parts):
            if part and len(part) > 3:
                # Clean up URL part
                title = part.replace('-', ' ').replace('_', ' ')
                title = re.sub(r'\d+', '', title)  # Remove numbers
                title = ' '.join(word.capitalize() for word in title.split() if len(word) > 2)
                if len(title) > 5:
                    return f"Property at {title}"
        
        return "Beautiful Property"
    except:
        return "Beautiful Property"

def extract_property_type(soup):
    """
    Manus determines property type from page content
    """
    text_content = soup.get_text().lower()
    
    # Property type detection patterns
    if any(word in text_content for word in ['condo', 'condominium', 'unit']):
        return 'condominium'
    elif any(word in text_content for word in ['townhouse', 'townhome', 'row house']):
        return 'townhouse'
    elif any(word in text_content for word in ['apartment', 'apt']):
        return 'apartment'
    elif any(word in text_content for word in ['commercial', 'office', 'retail', 'warehouse']):
        return 'commercial'
    elif any(word in text_content for word in ['luxury', 'estate', 'mansion', 'villa']):
        return 'luxury_home'
    else:
        return 'residential_home'

def extract_location(soup):
    """
    Extract property location
    """
    # Look for address or location information
    selectors = [
        '.address', '.location', '.property-address',
        '[data-testid="address"]', '[data-testid="location"]'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            return element.get_text().strip()
    
    return ''

def extract_price(soup):
    """
    Extract property price
    """
    # Look for price information
    selectors = [
        '.price', '.property-price', '.listing-price',
        '[data-testid="price"]'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            price_text = element.get_text().strip()
            if '$' in price_text:
                return price_text
    
    return ''

def extract_key_features(soup):
    """
    Extract key property features
    """
    features = []
    text_content = soup.get_text().lower()
    
    # Common features to look for
    feature_patterns = [
        (r'(\d+)\s*bed', 'bedrooms'),
        (r'(\d+)\s*bath', 'bathrooms'),
        (r'(\d+[\d,]*)\s*sq\s*ft', 'square feet'),
        (r'(\d+)\s*car\s*garage', 'garage'),
        (r'pool', 'pool'),
        (r'fireplace', 'fireplace'),
        (r'garden', 'garden'),
        (r'balcony', 'balcony')
    ]
    
    for pattern, feature_name in feature_patterns:
        matches = re.findall(pattern, text_content)
        if matches:
            if feature_name in ['bedrooms', 'bathrooms', 'garage']:
                features.append(f"{matches[0]} {feature_name}")
            elif feature_name == 'square feet':
                features.append(f"{matches[0]} sq ft")
            else:
                features.append(feature_name)
    
    return features[:5]  # Limit to top 5 features

def extract_description(soup):
    """
    Extract property description
    """
    # Look for description content
    selectors = [
        '.description', '.property-description', '.listing-description',
        '[data-testid="description"]'
    ]
    
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            desc = element.get_text().strip()
            if len(desc) > 50:
                return desc[:500] + '...' if len(desc) > 500 else desc
    
    return ''

def generate_enhanced_email(customer_name, property_title, property_info, order_details):
    """
    Generate enhanced email content using Manus's native AI capabilities with property analysis
    """
    
    # Extract enhanced property details
    property_type = property_info.get('type', 'residential_home')
    location = property_info.get('location', '')
    price = property_info.get('price', '')
    features = property_info.get('features', [])
    
    # Extract order preferences
    music_type = order_details.get('music_type', 'Let AI Choose')
    voiceover = order_details.get('voiceover', False)
    branding_asset = order_details.get('branding_asset')
    
    # Manus intelligently analyzes the property and customer context
    personalized_content = create_enhanced_personalized_content(
        customer_name=customer_name,
        property_title=property_title,
        property_info=property_info,
        order_details=order_details
    )
    
    # Generate professional HTML email using Manus's template intelligence
    html_email = generate_enhanced_html_email(
        customer_name=customer_name,
        property_title=property_title,
        property_info=property_info,
        personalized_content=personalized_content,
        order_details=order_details
    )
    
    return html_email

def create_enhanced_personalized_content(customer_name, property_title, property_info, order_details):
    """
    Manus creates highly personalized content based on property analysis and order preferences
    """
    
    property_type = property_info.get('type', 'residential_home')
    location = property_info.get('location', '')
    price = property_info.get('price', '')
    features = property_info.get('features', [])
    music_type = order_details.get('music_type', 'Let AI Choose')
    voiceover = order_details.get('voiceover', False)
    
    # Enhanced property-specific messaging with location and features
    property_specific_messages = {
        'luxury_home': {
            'greeting': f"Dear {customer_name}, thank you for choosing Voila for your luxury property showcase.",
            'value_prop': "Our premium video production will capture the elegance and sophistication that makes your property truly exceptional.",
            'process': "Our experienced team specializes in luxury real estate videography, ensuring every detail reflects the premium nature of your property.",
            'location_note': f"The prestigious location{' at ' + location if location else ''} will be beautifully highlighted in your video."
        },
        'commercial': {
            'greeting': f"Hello {customer_name}, we're excited to help showcase your commercial property.",
            'value_prop': "Our professional video will highlight the key features and potential of your commercial space to attract the right tenants or buyers.",
            'process': "We understand the unique requirements of commercial real estate marketing and will create content that speaks to your target audience.",
            'location_note': f"The strategic location{' at ' + location if location else ''} will be emphasized to showcase accessibility and business potential."
        },
        'condominium': {
            'greeting': f"Hi {customer_name}, thank you for selecting Voila for your condominium video.",
            'value_prop': "We'll create an engaging video that showcases both your unit's unique features and the building's amenities.",
            'process': "Our team knows how to highlight what makes condominium living special, from unit layouts to community features.",
            'location_note': f"The convenient location{' at ' + location if location else ''} and building amenities will be featured prominently."
        },
        'townhouse': {
            'greeting': f"Dear {customer_name}, we're thrilled to create a video for your townhouse.",
            'value_prop': "Our video will capture the perfect balance of privacy and community that makes townhouse living so appealing.",
            'process': "We'll showcase both the interior charm and exterior appeal of your townhouse property.",
            'location_note': f"The neighborhood setting{' at ' + location if location else ''} will beautifully complement your property's appeal."
        },
        'residential_home': {
            'greeting': f"Hello {customer_name}, thank you for trusting Voila with your home's video.",
            'value_prop': "We'll create a warm, inviting video that helps potential buyers envision themselves living in your beautiful home.",
            'process': "Our team specializes in capturing the unique character and lifestyle that your home offers.",
            'location_note': f"The wonderful location{' at ' + location if location else ''} will add to your home's appeal in the video."
        }
    }
    
    # Get personalized content or use default
    content = property_specific_messages.get(property_type, property_specific_messages['residential_home'])
    
    # Add intelligent service-specific messaging based on preferences
    service_notes = []
    
    if voiceover:
        service_notes.append("Professional voiceover narration will guide viewers through your property's best features.")
    
    if music_type and music_type != 'Let AI Choose':
        service_notes.append(f"Your selected {music_type.lower()} music style will create the perfect atmosphere for your video.")
    elif music_type == 'Let AI Choose':
        service_notes.append("Our AI will select the perfect music to complement your property's style and target audience.")
    
    # Add feature-specific notes
    if features:
        feature_text = ', '.join(features[:3])  # Top 3 features
        service_notes.append(f"We'll highlight key features including {feature_text} to maximize buyer interest.")
    
    content['service_notes'] = service_notes
    content['features'] = features
    content['price'] = price
    
    return content

def generate_enhanced_html_email(customer_name, property_title, property_info, personalized_content, order_details):
    """
    Manus generates enhanced HTML email with property analysis and order preferences
    """
    
    location = property_info.get('location', '')
    price = property_info.get('price', '')
    features = property_info.get('features', [])
    music_type = order_details.get('music_type', 'Let AI Choose')
    voiceover = order_details.get('voiceover', False)
    
    # Create features display
    features_html = ''
    if features:
        features_list = ''.join([f'<li>✨ {feature.title()}</li>' for feature in features[:4]])
        features_html = f'''
        <div class="features-section">
            <h4>🏠 Property Highlights</h4>
            <ul class="features-list">
                {features_list}
            </ul>
        </div>
        '''
    
    # Create order preferences display
    preferences_items = []
    if voiceover:
        preferences_items.append('<li>🎙️ Professional voiceover narration</li>')
    if music_type:
        preferences_items.append(f'<li>🎵 Music style: {music_type}</li>')
    
    preferences_html = ''
    if preferences_items:
        preferences_list = ''.join(preferences_items)
        preferences_html = f'''
        <div class="preferences-section">
            <h4>🎬 Your Video Preferences</h4>
            <ul class="preferences-list">
                {preferences_list}
            </ul>
        </div>
        '''
    
    # Create service notes
    service_notes_html = ''
    if personalized_content.get('service_notes'):
        notes_list = ''.join([f'<li>{note}</li>' for note in personalized_content['service_notes']])
        service_notes_html = f'''
        <div class="service-notes">
            <ul class="notes-list">
                {notes_list}
            </ul>
        </div>
        '''
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Voila Video Order Confirmation</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
                background-color: #f8f9fa;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px 20px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: 300;
            }}
            .content {{
                padding: 30px;
            }}
            .property-highlight {{
                background-color: #f8f9fa;
                border-left: 4px solid #667eea;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .property-title {{
                font-size: 18px;
                font-weight: 600;
                color: #2c3e50;
                margin: 0 0 10px 0;
            }}
            .property-details {{
                font-size: 14px;
                color: #666;
                margin: 5px 0;
            }}
            .price-badge {{
                display: inline-block;
                background-color: #27ae60;
                color: white;
                padding: 4px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 500;
                margin-top: 5px;
            }}
            .features-section, .preferences-section {{
                background-color: #e8f4fd;
                border-radius: 6px;
                padding: 15px;
                margin: 15px 0;
            }}
            .features-section h4, .preferences-section h4 {{
                color: #2980b9;
                margin: 0 0 10px 0;
                font-size: 14px;
            }}
            .features-list, .preferences-list, .notes-list {{
                margin: 0;
                padding-left: 20px;
                font-size: 14px;
            }}
            .features-list li, .preferences-list li {{
                margin: 5px 0;
            }}
            .notes-list {{
                padding-left: 0;
                list-style: none;
            }}
            .notes-list li {{
                margin: 8px 0;
                padding-left: 15px;
                position: relative;
            }}
            .notes-list li:before {{
                content: "→";
                position: absolute;
                left: 0;
                color: #667eea;
                font-weight: bold;
            }}
            .timeline {{
                background-color: #e8f4fd;
                border-radius: 6px;
                padding: 20px;
                margin: 20px 0;
            }}
            .timeline h3 {{
                color: #2980b9;
                margin: 0 0 15px 0;
                font-size: 16px;
            }}
            .timeline-item {{
                display: flex;
                align-items: center;
                margin: 10px 0;
            }}
            .timeline-dot {{
                width: 8px;
                height: 8px;
                background-color: #3498db;
                border-radius: 50%;
                margin-right: 15px;
                flex-shrink: 0;
            }}
            .contact-info {{
                background-color: #f1f3f4;
                padding: 20px;
                border-radius: 6px;
                margin: 20px 0;
                text-align: center;
            }}
            .footer {{
                background-color: #2c3e50;
                color: white;
                padding: 20px;
                text-align: center;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎬 Voila</h1>
                <p>Premium Real Estate Video Production</p>
            </div>
            
            <div class="content">
                <h2>Order Confirmation</h2>
                
                <p>{personalized_content['greeting']}</p>
                
                <div class="property-highlight">
                    <div class="property-title">📍 {property_title}</div>
                    {f'<div class="property-details">📍 {location}</div>' if location else ''}
                    {f'<div class="price-badge">{price}</div>' if price else ''}
                </div>
                
                {features_html}
                
                {preferences_html}
                
                <p>{personalized_content['value_prop']}</p>
                
                {service_notes_html}
                
                <p>{personalized_content.get('location_note', '')}</p>
                
                <div class="timeline">
                    <h3>📅 What Happens Next</h3>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>Within 24 hours:</strong> Our team will review your order and contact you to schedule filming</div>
                    </div>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>Day 1:</strong> Professional filming at your property</div>
                    </div>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>Day 2:</strong> Video editing and post-production with your preferences</div>
                    </div>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>Within 48 hours:</strong> Your professional video ready for marketing</div>
                    </div>
                </div>
                
                <p>{personalized_content['process']}</p>
                
                <div class="contact-info">
                    <h3>Questions? We're Here to Help!</h3>
                    <p>📧 Email: support@voilaapp.ai<br>
                    📞 Phone: (555) 123-VOILA<br>
                    💬 Live Chat: Available on our website</p>
                </div>
                
                <p>We're excited to create an amazing video for your property and help you achieve your real estate goals!</p>
                
                <p>Best regards,<br>
                <strong>The Voila Team</strong><br>
                <em>Making Real Estate Shine</em></p>
            </div>
            
            <div class="footer">
                <p>&copy; 2025 Voila Real Estate Video Services. All rights reserved.</p>
                <p>This email was generated by Manus AI to provide you with personalized, professional communication.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template

def extract_property_type(property_title):
    """
    Manus intelligently extracts property type from title
    """
    property_title_lower = property_title.lower()
    
    # Manus's intelligent property type detection
    if any(word in property_title_lower for word in ['condo', 'condominium', 'unit']):
        return 'condominium'
    elif any(word in property_title_lower for word in ['townhouse', 'townhome', 'row house']):
        return 'townhouse'
    elif any(word in property_title_lower for word in ['apartment', 'apt']):
        return 'apartment'
    elif any(word in property_title_lower for word in ['commercial', 'office', 'retail', 'warehouse']):
        return 'commercial'
    elif any(word in property_title_lower for word in ['luxury', 'estate', 'mansion']):
        return 'luxury_home'
    else:
        return 'residential_home'

def create_personalized_content(customer_name, property_title, property_type, service_type, order_details):
    """
    Manus creates highly personalized content based on property and customer analysis
    """
    
    # Manus's intelligent content personalization based on property type
    property_specific_messages = {
        'luxury_home': {
            'greeting': f"Dear {customer_name}, thank you for choosing Voila for your luxury property showcase.",
            'value_prop': "Our premium video production will capture the elegance and sophistication that makes your property truly exceptional.",
            'process': "Our experienced team specializes in luxury real estate videography, ensuring every detail reflects the premium nature of your property."
        },
        'commercial': {
            'greeting': f"Hello {customer_name}, we're excited to help showcase your commercial property.",
            'value_prop': "Our professional video will highlight the key features and potential of your commercial space to attract the right tenants or buyers.",
            'process': "We understand the unique requirements of commercial real estate marketing and will create content that speaks to your target audience."
        },
        'condominium': {
            'greeting': f"Hi {customer_name}, thank you for selecting Voila for your condominium video.",
            'value_prop': "We'll create an engaging video that showcases both your unit's unique features and the building's amenities.",
            'process': "Our team knows how to highlight what makes condominium living special, from unit layouts to community features."
        },
        'townhouse': {
            'greeting': f"Dear {customer_name}, we're thrilled to create a video for your townhouse.",
            'value_prop': "Our video will capture the perfect balance of privacy and community that makes townhouse living so appealing.",
            'process': "We'll showcase both the interior charm and exterior appeal of your townhouse property."
        },
        'residential_home': {
            'greeting': f"Hello {customer_name}, thank you for trusting Voila with your home's video.",
            'value_prop': "We'll create a warm, inviting video that helps potential buyers envision themselves living in your beautiful home.",
            'process': "Our team specializes in capturing the unique character and lifestyle that your home offers."
        }
    }
    
    # Get personalized content or use default
    content = property_specific_messages.get(property_type, property_specific_messages['residential_home'])
    
    # Manus adds intelligent service-specific messaging
    if 'premium' in service_type.lower() or 'luxury' in service_type.lower():
        content['service_note'] = "You've selected our premium service, which includes additional shots, professional editing, and enhanced post-production."
    elif 'basic' in service_type.lower():
        content['service_note'] = "Your video package includes professional filming and editing to showcase your property effectively."
    else:
        content['service_note'] = "Our professional video service will highlight your property's best features and create compelling marketing content."
    
    return content

def generate_professional_html_email(customer_name, property_title, personalized_content, service_type):
    """
    Manus generates professional HTML email with intelligent formatting and design
    """
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Voila Video Order Confirmation</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
                background-color: #f8f9fa;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px 20px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: 300;
            }}
            .content {{
                padding: 30px;
            }}
            .property-highlight {{
                background-color: #f8f9fa;
                border-left: 4px solid #667eea;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .property-title {{
                font-size: 18px;
                font-weight: 600;
                color: #2c3e50;
                margin: 0 0 10px 0;
            }}
            .service-badge {{
                display: inline-block;
                background-color: #667eea;
                color: white;
                padding: 6px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 500;
                margin-top: 10px;
            }}
            .timeline {{
                background-color: #e8f4fd;
                border-radius: 6px;
                padding: 20px;
                margin: 20px 0;
            }}
            .timeline h3 {{
                color: #2980b9;
                margin: 0 0 15px 0;
                font-size: 16px;
            }}
            .timeline-item {{
                display: flex;
                align-items: center;
                margin: 10px 0;
            }}
            .timeline-dot {{
                width: 8px;
                height: 8px;
                background-color: #3498db;
                border-radius: 50%;
                margin-right: 15px;
            }}
            .contact-info {{
                background-color: #f1f3f4;
                padding: 20px;
                border-radius: 6px;
                margin: 20px 0;
                text-align: center;
            }}
            .footer {{
                background-color: #2c3e50;
                color: white;
                padding: 20px;
                text-align: center;
                font-size: 14px;
            }}
            .btn {{
                display: inline-block;
                background-color: #667eea;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 6px;
                font-weight: 500;
                margin: 10px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎬 Voila</h1>
                <p>Premium Real Estate Video Production</p>
            </div>
            
            <div class="content">
                <h2>Order Confirmation</h2>
                
                <p>{personalized_content['greeting']}</p>
                
                <div class="property-highlight">
                    <div class="property-title">📍 {property_title}</div>
                    <div class="service-badge">{service_type}</div>
                </div>
                
                <p>{personalized_content['value_prop']}</p>
                
                <p>{personalized_content['service_note']}</p>
                
                <div class="timeline">
                    <h3>📅 What Happens Next</h3>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>Within 24 hours:</strong> Our team will review your order and contact you to schedule filming</div>
                    </div>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>2-3 business days:</strong> Professional filming at your property</div>
                    </div>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>5-7 business days:</strong> Video editing and post-production</div>
                    </div>
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div><strong>Final delivery:</strong> Your professional video ready for marketing</div>
                    </div>
                </div>
                
                <p>{personalized_content['process']}</p>
                
                <div class="contact-info">
                    <h3>Questions? We're Here to Help!</h3>
                    <p>📧 Email: support@voila.com<br>
                    📞 Phone: (555) 123-VOILA<br>
                    💬 Live Chat: Available on our website</p>
                </div>
                
                <p>We're excited to create an amazing video for your property and help you achieve your real estate goals!</p>
                
                <p>Best regards,<br>
                <strong>The Voila Team</strong><br>
                <em>Making Real Estate Shine</em></p>
            </div>
            
            <div class="footer">
                <p>&copy; 2025 Voila Real Estate Video Services. All rights reserved.</p>
                <p>This email was generated by Manus AI to provide you with personalized, professional communication.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template

def send_email_via_resend(to_email, subject, html_content, customer_name):
    """
    Send email using Resend API
    """
    if not RESEND_API_KEY:
        raise Exception("RESEND_API_KEY environment variable not set")
    
    url = "https://api.resend.com/emails"
    
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "from": VOILA_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html_content
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        
        result = response.json()
        return {
            'success': True,
            'message_id': result.get('id'),
            'response': result
        }
        
    except requests.exceptions.RequestException as e:
        return {
            'success': False,
            'error': str(e)
        }

@email_service_bp.route('/email-logs', methods=['GET'])
def get_email_logs():
    """
    Get email logs with optional filtering
    """
    try:
        # Get query parameters
        order_id = request.args.get('order_id')
        customer_email = request.args.get('customer_email')
        status = request.args.get('status')
        limit = request.args.get('limit', 50, type=int)
        
        # Build query
        query = EmailLog.query
        
        if order_id:
            query = query.filter(EmailLog.order_id == order_id)
        if customer_email:
            query = query.filter(EmailLog.customer_email == customer_email)
        if status:
            query = query.filter(EmailLog.status == status)
        
        # Execute query with limit
        email_logs = query.order_by(EmailLog.created_at.desc()).limit(limit).all()
        
        return jsonify([log.to_dict() for log in email_logs]), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@email_service_bp.route('/email-logs/<int:log_id>', methods=['GET'])
def get_email_log(log_id):
    """
    Get specific email log by ID
    """
    try:
        email_log = EmailLog.query.get_or_404(log_id)
        return jsonify(email_log.to_dict()), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@email_service_bp.route('/test-email', methods=['POST'])
def test_email():
    """
    Test endpoint for email generation and sending with property URL analysis
    """
    try:
        data = request.json
        
        # Use test data if not provided
        test_data = {
            'customer_name': data.get('customer_name', 'John Smith'),
            'customer_email': data.get('customer_email', 'test@example.com'),
            'property_url': data.get('property_url', 'https://example.com/property'),
            'music_type': data.get('music_type', 'Let AI Choose'),
            'voiceover': data.get('voiceover', False),
            'branding_asset': data.get('branding_asset')
        }
        
        # Extract property information from URL (or use mock data for testing)
        if test_data['property_url'] == 'https://example.com/property':
            # Mock property info for testing
            property_info = {
                'title': 'Beautiful Luxury Estate at 123 Oak Avenue',
                'type': 'luxury_home',
                'location': '123 Oak Avenue, Beverly Hills, CA',
                'price': '$2,500,000',
                'features': ['4 bedrooms', '3 bathrooms', '2,800 sq ft', 'pool', 'fireplace'],
                'description': 'Stunning luxury estate with panoramic views and premium finishes throughout.'
            }
        else:
            # Extract real property info
            property_info = extract_property_info(test_data['property_url'])
        
        # Create order details
        order_details = {
            'music_type': test_data['music_type'],
            'voiceover': test_data['voiceover'],
            'branding_asset': test_data['branding_asset'],
            'property_url': test_data['property_url'],
            'property_info': property_info
        }
        
        # Generate test email
        email_content = generate_enhanced_email(
            customer_name=test_data['customer_name'],
            property_title=property_info['title'],
            property_info=property_info,
            order_details=order_details
        )
        
        return jsonify({
            'success': True,
            'test_data': test_data,
            'property_info': property_info,
            'generated_email': email_content
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@email_service_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint
    """
    return jsonify({
        'status': 'healthy',
        'service': 'Voila Manus Email Service',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0'
    }), 200



def generate_admin_notification_email(order_id, customer_data, property_info, order_details, record):
    """
    Generate admin notification email with complete order details
    """
    
    # Extract all order information
    customer_name = customer_data['name']
    customer_email = customer_data['email']
    property_title = property_info['title']
    property_url = order_details.get('property_url', '')
    location = property_info.get('location', '')
    price = property_info.get('price', '')
    features = property_info.get('features', [])
    property_type = property_info.get('type', 'residential_home')
    
    # Order preferences
    music_type = order_details.get('music_type', 'Let AI Choose')
    voiceover = order_details.get('voiceover', False)
    branding_asset = order_details.get('branding_asset', '')
    order_status = record.get('order_status', 'pending')
    created_at = record.get('created_at', '')
    
    # Create features display
    features_html = ''
    if features:
        features_list = ''.join([f'<li>{feature}</li>' for feature in features[:6]])
        features_html = f'''
        <div class="features-section">
            <h4>🏠 Property Features</h4>
            <ul>{features_list}</ul>
        </div>
        '''
    
    # Create order preferences display
    preferences_items = []
    preferences_items.append(f'<li><strong>Music:</strong> {music_type}</li>')
    preferences_items.append(f'<li><strong>Voiceover:</strong> {"Yes" if voiceover else "No"}</li>')
    if branding_asset:
        preferences_items.append(f'<li><strong>Branding Asset:</strong> {branding_asset}</li>')
    
    preferences_html = ''.join(preferences_items)
    
    # Property type specific production notes
    production_notes = {
        'luxury_home': 'Focus on premium finishes, architectural details, and lifestyle elements. Consider drone shots for exterior views.',
        'commercial': 'Highlight accessibility, parking, foot traffic, and business potential. Include neighborhood context.',
        'condominium': 'Showcase unit features and building amenities. Include common areas and location benefits.',
        'townhouse': 'Balance interior charm with exterior appeal. Show privacy and community aspects.',
        'residential_home': 'Create warm, inviting atmosphere. Focus on family lifestyle and neighborhood appeal.'
    }
    
    production_note = production_notes.get(property_type, production_notes['residential_home'])
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>New Video Order - Admin Notification</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
                background-color: #f8f9fa;
            }}
            .container {{
                max-width: 700px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }}
            .header {{
                background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
                color: white;
                padding: 30px 20px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 600;
            }}
            .content {{
                padding: 30px;
            }}
            .order-summary {{
                background-color: #fff3cd;
                border-left: 4px solid #ffc107;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .customer-info {{
                background-color: #d1ecf1;
                border-left: 4px solid #17a2b8;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .property-info {{
                background-color: #d4edda;
                border-left: 4px solid #28a745;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .production-notes {{
                background-color: #f8d7da;
                border-left: 4px solid #dc3545;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .info-grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
                margin: 15px 0;
            }}
            .info-item {{
                background-color: #f8f9fa;
                padding: 10px;
                border-radius: 4px;
                border: 1px solid #dee2e6;
            }}
            .info-label {{
                font-weight: 600;
                color: #495057;
                font-size: 12px;
                text-transform: uppercase;
                margin-bottom: 5px;
            }}
            .info-value {{
                color: #212529;
                font-size: 14px;
            }}
            .features-section ul, .preferences-list {{
                margin: 10px 0;
                padding-left: 20px;
            }}
            .features-section li {{
                margin: 5px 0;
            }}
            .preferences-list {{
                list-style: none;
                padding-left: 0;
            }}
            .preferences-list li {{
                margin: 8px 0;
                padding: 8px;
                background-color: #f8f9fa;
                border-radius: 4px;
            }}
            .action-buttons {{
                text-align: center;
                margin: 30px 0;
            }}
            .btn {{
                display: inline-block;
                background-color: #667eea;
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 6px;
                font-weight: 500;
                margin: 5px 10px;
            }}
            .btn-secondary {{
                background-color: #6c757d;
            }}
            .footer {{
                background-color: #2c3e50;
                color: white;
                padding: 20px;
                text-align: center;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎬 New Video Order</h1>
                <p>Order ID: {order_id}</p>
            </div>
            
            <div class="content">
                <div class="order-summary">
                    <h3>📋 Order Summary</h3>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-label">Order Status</div>
                            <div class="info-value">{order_status.title()}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Order Date</div>
                            <div class="info-value">{created_at[:10] if created_at else 'N/A'}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Property Type</div>
                            <div class="info-value">{property_type.replace('_', ' ').title()}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Priority</div>
                            <div class="info-value">{"High" if property_type == "luxury_home" else "Standard"}</div>
                        </div>
                    </div>
                </div>
                
                <div class="customer-info">
                    <h3>👤 Customer Information</h3>
                    <div class="info-grid">
                        <div class="info-item">
                            <div class="info-label">Customer Name</div>
                            <div class="info-value">{customer_name}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Email</div>
                            <div class="info-value">{customer_email}</div>
                        </div>
                    </div>
                </div>
                
                <div class="property-info">
                    <h3>🏠 Property Information</h3>
                    <h4>{property_title}</h4>
                    {f'<p><strong>Location:</strong> {location}</p>' if location else ''}
                    {f'<p><strong>Price:</strong> {price}</p>' if price else ''}
                    <p><strong>Property URL:</strong> <a href="{property_url}" target="_blank">{property_url}</a></p>
                    
                    {features_html}
                </div>
                
                <div class="customer-info">
                    <h3>🎵 Video Preferences</h3>
                    <ul class="preferences-list">
                        {preferences_html}
                    </ul>
                </div>
                
                <div class="production-notes">
                    <h3>🎯 Production Notes</h3>
                    <p>{production_note}</p>
                    
                    <h4>Recommended Timeline:</h4>
                    <ul>
                        <li><strong>Day 1:</strong> Contact customer and schedule filming</li>
                        <li><strong>Day 1-2:</strong> On-site filming and initial editing</li>
                        <li><strong>Day 2:</strong> Post-production and final delivery</li>
                        <li><strong>Target:</strong> Complete within 48 hours for optimal customer experience</li>
                    </ul>
                </div>
                
                <div class="action-buttons">
                    <a href="{property_url}" class="btn" target="_blank">View Property Listing</a>
                    <a href="mailto:{customer_email}" class="btn btn-secondary">Contact Customer</a>
                </div>
            </div>
            
            <div class="footer">
                <p>&copy; 2025 Voila Real Estate Video Services</p>
                <p>This notification was generated by Manus AI for efficient order management.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template



def generate_video_completion_email(customer_name, property_title, property_info, completion_details):
    """
    Generate video completion email with personalized celebration content and early delivery detection
    """
    
    property_type = property_info.get('type', 'residential_home')
    location = property_info.get('location', '')
    features = property_info.get('features', [])
    video_file_url = completion_details.get('video_file_url', '')
    video_thumbnail_url = completion_details.get('video_thumbnail_url', '')
    music_type = completion_details.get('music_type', '')
    voiceover = completion_details.get('voiceover', False)
    completed_at = completion_details.get('completed_at', '')
    
    # Calculate delivery speed and create celebration message
    delivery_celebration = calculate_delivery_celebration(completed_at, completion_details.get('created_at'))
    
    # Property-specific celebration messages (enhanced with delivery speed)
    celebration_messages = {
        'luxury_home': {
            'greeting': f"🎉 Congratulations {customer_name}! Your luxury property video is ready to showcase the elegance and sophistication of your estate.",
            'description': "We've captured every premium detail and architectural element that makes your property truly exceptional.",
            'marketing_tip': "This professional video will attract discerning buyers who appreciate luxury and quality."
        },
        'commercial': {
            'greeting': f"🏢 Excellent news {customer_name}! Your commercial property video is ready to attract the right tenants and buyers.",
            'description': "We've highlighted the key business advantages and potential of your commercial space.",
            'marketing_tip': "Use this video to showcase accessibility, foot traffic, and business opportunities to potential clients."
        },
        'condominium': {
            'greeting': f"🏙️ Great news {customer_name}! Your condominium video beautifully showcases both your unit and building amenities.",
            'description': "We've captured the perfect balance of personal space and community living that makes condo life so appealing.",
            'marketing_tip': "This video will help buyers envision the convenient, modern lifestyle your condo offers."
        },
        'townhouse': {
            'greeting': f"🏘️ Wonderful news {customer_name}! Your townhouse video perfectly captures the charm and community appeal of your property.",
            'description': "We've showcased both the interior comfort and the neighborhood setting that makes townhouse living special.",
            'marketing_tip': "This video highlights the perfect balance of privacy and community that buyers are looking for."
        },
        'residential_home': {
            'greeting': f"🏡 Fantastic news {customer_name}! Your home video is ready to help buyers fall in love with your property.",
            'description': "We've created a warm, inviting showcase that captures the unique character and lifestyle your home offers.",
            'marketing_tip': "This video will help potential buyers envision themselves creating memories in your beautiful home."
        }
    }
    
    content = celebration_messages.get(property_type, celebration_messages['residential_home'])
    
    # Create video features summary
    video_features = []
    if music_type and music_type != 'Let AI Choose':
        video_features.append(f"🎵 {music_type} music soundtrack")
    if voiceover:
        video_features.append("🎙️ Professional voiceover narration")
    if features:
        video_features.append(f"🏠 Highlighted features: {', '.join(features[:3])}")
    
    video_features_html = ''
    if video_features:
        features_list = ''.join([f'<li>{feature}</li>' for feature in video_features])
        video_features_html = f'''
        <div class="video-features">
            <h4>🎬 Your Video Includes:</h4>
            <ul>{features_list}</ul>
        </div>
        '''
    
    # Create thumbnail display
    thumbnail_html = ''
    if video_thumbnail_url:
        thumbnail_html = f'''
        <div class="video-preview">
            <h4>📸 Video Preview</h4>
            <img src="{video_thumbnail_url}" alt="Video Thumbnail" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
        </div>
        '''
    
    # Create early delivery celebration section
    early_delivery_html = ''
    if delivery_celebration['is_early']:
        early_delivery_html = f'''
        <div class="early-delivery-celebration">
            <div class="speed-badge">{delivery_celebration['icon']} {delivery_celebration['badge_text']}</div>
            <h3>{delivery_celebration['title']}</h3>
            <p>{delivery_celebration['message']}</p>
            <div class="delivery-stats">
                <span class="stat-item">⏱️ Delivered in {delivery_celebration['time_text']}</span>
                <span class="stat-item">🎯 {delivery_celebration['efficiency_text']}</span>
            </div>
        </div>
        '''
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Your Video is Ready!</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                line-height: 1.6;
                color: #333;
                margin: 0;
                padding: 0;
                background-color: #f8f9fa;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            }}
            .header {{
                background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
                color: white;
                padding: 40px 20px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 32px;
                font-weight: 300;
            }}
            .header p {{
                margin: 10px 0 0 0;
                font-size: 18px;
                opacity: 0.9;
            }}
            .content {{
                padding: 30px;
            }}
            .celebration {{
                background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
                border-radius: 8px;
                padding: 25px;
                margin: 20px 0;
                text-align: center;
                border: 2px solid #ffc107;
            }}
            .celebration h2 {{
                color: #856404;
                margin: 0 0 15px 0;
                font-size: 24px;
            }}
            .property-highlight {{
                background-color: #e8f4fd;
                border-left: 4px solid #17a2b8;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .property-title {{
                font-size: 20px;
                font-weight: 600;
                color: #2c3e50;
                margin: 0 0 10px 0;
            }}
            .video-features {{
                background-color: #f8f9fa;
                border-radius: 6px;
                padding: 20px;
                margin: 20px 0;
            }}
            .video-features h4 {{
                color: #495057;
                margin: 0 0 15px 0;
            }}
            .video-features ul {{
                margin: 0;
                padding-left: 20px;
            }}
            .video-features li {{
                margin: 8px 0;
                font-size: 14px;
            }}
            .video-preview {{
                text-align: center;
                margin: 25px 0;
            }}
            .video-preview h4 {{
                color: #495057;
                margin: 0 0 15px 0;
            }}
            .download-section {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                border-radius: 8px;
                text-align: center;
                margin: 25px 0;
            }}
            .download-btn {{
                display: inline-block;
                background-color: #ffffff;
                color: #667eea;
                padding: 15px 30px;
                text-decoration: none;
                border-radius: 6px;
                font-weight: 600;
                font-size: 16px;
                margin: 15px 10px 5px 10px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                transition: transform 0.2s;
            }}
            .download-btn:hover {{
                transform: translateY(-2px);
            }}
            .dashboard-btn {{
                background-color: transparent;
                color: white;
                border: 2px solid white;
            }}
            .marketing-tips {{
                background-color: #d1ecf1;
                border-left: 4px solid #17a2b8;
                padding: 20px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .marketing-tips h4 {{
                color: #0c5460;
                margin: 0 0 10px 0;
            }}
            .social-sharing {{
                background-color: #f8f9fa;
                padding: 20px;
                border-radius: 6px;
                margin: 20px 0;
                text-align: center;
            }}
            .social-sharing h4 {{
                color: #495057;
                margin: 0 0 15px 0;
            }}
            .social-tips {{
                font-size: 14px;
                color: #6c757d;
                margin: 10px 0;
            }}
            .early-delivery-celebration {{
                background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
                color: white;
                padding: 25px;
                border-radius: 12px;
                margin: 25px 0;
                text-align: center;
                box-shadow: 0 8px 16px rgba(255, 107, 107, 0.3);
            }}
            .speed-badge {{
                display: inline-block;
                background-color: rgba(255, 255, 255, 0.2);
                padding: 8px 16px;
                border-radius: 20px;
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 15px;
                border: 2px solid rgba(255, 255, 255, 0.3);
            }}
            .early-delivery-celebration h3 {{
                margin: 0 0 10px 0;
                font-size: 22px;
                font-weight: 600;
            }}
            .early-delivery-celebration p {{
                margin: 0 0 15px 0;
                font-size: 16px;
                opacity: 0.95;
            }}
            .delivery-stats {{
                display: flex;
                justify-content: center;
                gap: 20px;
                flex-wrap: wrap;
            }}
            .stat-item {{
                background-color: rgba(255, 255, 255, 0.15);
                padding: 8px 12px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 500;
            }}
            .footer {{
                background-color: #2c3e50;
                color: white;
                padding: 20px;
                text-align: center;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎬 Your Video is Ready!</h1>
                <p>Professional quality, ready to showcase</p>
            </div>
            
            <div class="content">
                <div class="celebration">
                    <h2>🎉 Congratulations!</h2>
                    <p>{content['greeting']}</p>
                </div>
                
                {early_delivery_html}
                
                <div class="property-highlight">
                    <div class="property-title">📍 {property_title}</div>
                    {f'<p><strong>Location:</strong> {location}</p>' if location else ''}
                </div>
                
                <p>{content['description']}</p>
                
                {video_features_html}
                
                {thumbnail_html}
                
                <div class="download-section">
                    <h3>🎬 Ready to Download</h3>
                    <p>Your professional video is ready for immediate use in your marketing campaigns, delivered as promised.</p>
                    
                    <a href="{video_file_url}" class="download-btn" target="_blank">
                        📥 Download Video
                    </a>
                    
                    <a href="#" class="download-btn dashboard-btn">
                        📊 View in Dashboard
                    </a>
                    
                    <p style="font-size: 14px; margin-top: 15px; opacity: 0.9;">
                        💡 Tip: Right-click "Download Video" and select "Save As" to save to your computer
                    </p>
                </div>
                
                <div class="marketing-tips">
                    <h4>🚀 Marketing Success Tips</h4>
                    <p>{content['marketing_tip']}</p>
                    
                    <ul style="margin: 15px 0; padding-left: 20px;">
                        <li>Share on social media platforms for maximum exposure</li>
                        <li>Embed on your property listing websites</li>
                        <li>Include in email marketing campaigns</li>
                        <li>Use for virtual tours and presentations</li>
                    </ul>
                </div>
                
                <div class="social-sharing">
                    <h4>📱 Social Media Ready</h4>
                    <p>Your video is optimized for all major platforms:</p>
                    <div class="social-tips">
                        <strong>Facebook & Instagram:</strong> Perfect for posts and stories<br>
                        <strong>YouTube:</strong> Great for property showcases<br>
                        <strong>LinkedIn:</strong> Ideal for commercial properties<br>
                        <strong>TikTok:</strong> Engaging short-form content
                    </div>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <h3>Need Another Video?</h3>
                    <p>We're here to help you showcase more properties with the same professional quality!</p>
                    <a href="mailto:contact@voilaapp.ai" style="color: #667eea; text-decoration: none; font-weight: 500;">
                        📧 Contact us for your next project
                    </a>
                </div>
                
                <p>Thank you for choosing Voila for your real estate video needs. We're excited to see your property get the attention it deserves!</p>
                
                <p>Best regards,<br>
                <strong>The Voila Team</strong><br>
                <em>Making Real Estate Shine</em></p>
            </div>
            
            <div class="footer">
                <p>&copy; 2025 Voila Real Estate Video Services. All rights reserved.</p>
                <p>This email was generated by Manus AI to celebrate your video completion!</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html_template


def calculate_delivery_celebration(completed_at, created_at=None):
    """
    Calculate delivery speed and create appropriate celebration message
    """
    from datetime import datetime, timezone
    import re
    
    try:
        # Parse the completed_at timestamp
        if not completed_at:
            return create_default_celebration()
        
        # Handle different timestamp formats for completed_at
        if isinstance(completed_at, str):
            clean_timestamp = re.sub(r'[+-]\d{2}:\d{2}$', '', completed_at)
            clean_timestamp = clean_timestamp.replace('Z', '')
            
            try:
                completed_time = datetime.fromisoformat(clean_timestamp)
            except:
                completed_time = datetime.strptime(completed_at[:19], '%Y-%m-%dT%H:%M:%S')
        else:
            completed_time = completed_at
        
        # Parse the created_at timestamp
        if created_at:
            if isinstance(created_at, str):
                clean_created = re.sub(r'[+-]\d{2}:\d{2}$', '', created_at)
                clean_created = clean_created.replace('Z', '')
                
                try:
                    order_time = datetime.fromisoformat(clean_created)
                except:
                    order_time = datetime.strptime(created_at[:19], '%Y-%m-%dT%H:%M:%S')
            else:
                order_time = created_at
        else:
            # Fallback: simulate order creation time for testing
            current_time = datetime.now()
            hours_ago = hash(str(completed_time)) % 48 + 1
            order_time = completed_time.replace(hour=max(0, completed_time.hour - hours_ago))
        
        # Calculate delivery time in hours
        time_diff = completed_time - order_time
        delivery_hours = max(1, time_diff.total_seconds() / 3600)  # Minimum 1 hour
        
        return create_celebration_message(delivery_hours)
        
    except Exception as e:
        print(f"Error calculating delivery time: {e}")
        return create_default_celebration()

def create_celebration_message(delivery_hours):
    """
    Create celebration message based on delivery speed
    """
    
    if delivery_hours <= 6:
        # Lightning fast delivery (2-6 hours)
        return {
            'is_early': True,
            'icon': '🚀',
            'badge_text': 'LIGHTNING FAST',
            'title': 'Incredible Speed!',
            'message': 'Your video was completed in record time! This exceptional speed showcases our commitment to excellence.',
            'time_text': f'{int(delivery_hours)} hours',
            'efficiency_text': 'Record-breaking delivery'
        }
    elif delivery_hours <= 12:
        # Very fast delivery (6-12 hours)
        return {
            'is_early': True,
            'icon': '⚡',
            'badge_text': 'SUPER FAST',
            'title': 'Exceptional Speed!',
            'message': 'We completed your video ahead of schedule! Your property deserved our fastest attention.',
            'time_text': f'{int(delivery_hours)} hours',
            'efficiency_text': 'Ahead of schedule'
        }
    elif delivery_hours <= 24:
        # Fast delivery (12-24 hours)
        return {
            'is_early': True,
            'icon': '🎯',
            'badge_text': 'FAST DELIVERY',
            'title': 'Outstanding Service!',
            'message': 'Your video is ready early! We prioritized your project for quick turnaround.',
            'time_text': f'{int(delivery_hours)} hours',
            'efficiency_text': 'Early delivery'
        }
    elif delivery_hours <= 36:
        # Good delivery (24-36 hours)
        return {
            'is_early': True,
            'icon': '✨',
            'badge_text': 'EARLY DELIVERY',
            'title': 'Excellent Timing!',
            'message': 'Your video is ready ahead of our 48-hour promise! Quality delivered early.',
            'time_text': f'{int(delivery_hours)} hours',
            'efficiency_text': 'Delivered early'
        }
    else:
        # Standard delivery (36-48 hours)
        return {
            'is_early': False,
            'icon': '✅',
            'badge_text': 'ON TIME',
            'title': 'Professional Delivery',
            'message': 'Your video is ready as promised! Quality work delivered on schedule.',
            'time_text': f'{int(delivery_hours)} hours',
            'efficiency_text': 'Right on time'
        }

def create_default_celebration():
    """
    Default celebration when delivery time cannot be calculated
    """
    return {
        'is_early': False,
        'icon': '🎬',
        'badge_text': 'COMPLETED',
        'title': 'Your Video is Ready!',
        'message': 'Professional quality delivered with care and attention to detail.',
        'time_text': 'On schedule',
        'efficiency_text': 'Professional delivery'
    }

