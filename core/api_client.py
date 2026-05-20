import httpx
from core.config import settings
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

async def fetch_from_sports_api(endpoint: str, extra_params: dict = None):
    """
    Fetch data from TheSports API
    
    Required environment variables:
    - SPORTS_API_BASE_URL: Base URL of the API
    - SPORTS_USER_TOKEN: User token for authentication
    - SPORTS_SECRET_TOKEN: Secret token for authentication
    
    Args:
        endpoint: API endpoint path
        extra_params: Optional dictionary of additional query parameters to pass to the API
    """
    try:
        url = f"{settings.SPORTS_API_BASE_URL}/{endpoint}"
        
        # TheSports API uses query parameters for authentication, not headers
        params = {
            "user": settings.SPORTS_USER_TOKEN,
            "secret": settings.SPORTS_SECRET_TOKEN
        }
        
        # Add any extra query parameters if provided
        if extra_params:
            params.update(extra_params)
        
        # Enhanced logging for debugging
        logger.info(f"Fetching from Sports API: {url}")
        logger.info(f"Auth params: user={settings.SPORTS_USER_TOKEN}, secret={settings.SPORTS_SECRET_TOKEN[:10]}...")
        logger.info(f"Full URL with params: {url}?user={settings.SPORTS_USER_TOKEN}&secret={settings.SPORTS_SECRET_TOKEN[:10]}...")
        
        print(f"🔍 [API Client] Making request to: {url}")
        print(f"🔍 [API Client] User token: {settings.SPORTS_USER_TOKEN}")
        print(f"🔍 [API Client] Secret token (first 10 chars): {settings.SPORTS_SECRET_TOKEN[:10]}...")
        print(f"🔍 [API Client] Full secret token: {settings.SPORTS_SECRET_TOKEN}")

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, params=params)
            
            # Log response details for debugging
            logger.info(f"Sports API response status: {response.status_code}")
            print(f"🔍 [API Client] Response status: {response.status_code}")
            
            # Log full response for debugging
            try:
                response_text = response.text
                print(f"🔍 [API Client] Response text: {response_text[:500]}...")  # First 500 chars
            except:
                pass
            
            if response.status_code == 401:
                logger.error(f"Unauthorized access to Sports API. Check your credentials.")
                raise HTTPException(
                    status_code=401,
                    detail="Sports API authentication failed. Please check your API credentials in the .env file."
                )
            
            response.raise_for_status()
            data = response.json()
            
            # Check if the response contains an error message (some APIs return 200 with error in body)
            if isinstance(data, dict) and "err" in data:
                error_msg = data.get('err', 'Unknown error')
                logger.error(f"Sports API returned error: {error_msg}")
                print(f"❌ [API Client] Sports API error: {error_msg}")
                print(f"❌ [API Client] Full response: {data}")
                
                # Check if it's an IP authorization error
                if "IP" in error_msg or "authorized" in error_msg or "whitelist" in error_msg:
                    print(f"⚠️ [API Client] IP authorization issue detected!")
                    print(f"⚠️ [API Client] Please verify your server's public IP is whitelisted in TheSports API dashboard")
                    print(f"⚠️ [API Client] Your server's public IP is what TheSports API sees, not 127.0.0.1")
                
                raise HTTPException(
                    status_code=401,
                    detail=f"Sports API Error: {error_msg}. Please verify your API credentials (SPORTS_USER_TOKEN and SPORTS_SECRET_TOKEN) in the .env file and ensure your server's public IP is whitelisted."
                )
            
            return data
            
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error from Sports API: {e.response.status_code} - {e.response.text}")
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Sports API error: {e.response.text}"
        )
    except Exception as e:
        logger.error(f"Error fetching from Sports API: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch from Sports API: {str(e)}"
        )
