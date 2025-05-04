#!/usr/bin/env python3
import json
import re
import logging
from typing import Optional, Dict, Any, List
from mcp.server.fastmcp import FastMCP, Context
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("quote-server")

mcp = FastMCP("quote-server")

def get_local_tz(local_tz_override: str | None = None) -> ZoneInfo:
    logger.info("Getting local timezone")
    
    # Get local timezone from datetime.now()
    tzinfo = datetime.now().astimezone(tz=None).tzinfo
    if tzinfo is not None:
        tz_str = str(tzinfo)
        if tz_str == "CST":
            tz_str = "America/Chicago" 
        
        logger.info(f"Local timezone detected: {tz_str}")
        return ZoneInfo(tz_str)
    else:
        logger.error("Failed to get local timezone")
        raise ValueError('get local timezone failed')
        

def get_zoneinfo(timezone_name: str) -> ZoneInfo:
    logger.info(f"Getting ZoneInfo for timezone: {timezone_name}")
    try:
        zone = ZoneInfo(timezone_name)
        logger.info(f"Successfully created ZoneInfo for {timezone_name}")
        return zone
    except Exception as e:
        logger.error(f"Invalid timezone: {str(e)}")
        raise ValueError(f"Invalid timezone: {str(e)}")

def update_docstring_with_info(func):
    """更新函数的docstring，"""
    logger.info(f"Updating docstring for function: {func.__name__}")
    local_tz = str(get_local_tz())
    
    if func.__doc__:
        func.__doc__ = func.__doc__.format(
            local_tz=local_tz
        )
        logger.info(f"Docstring updated with local timezone: {local_tz}")
    return func

# Product price database (for demo purposes)
PRODUCT_PRICES = {
    "08-50-0113": {"unit_price": 1.25, "currency": "USD", "min_order": 1000},
    "22-01-1042": {"unit_price": 3.75, "currency": "USD", "min_order": 500},
    "42816-0212": {"unit_price": 15.50, "currency": "USD", "min_order": 100},
}

def extract_product_info(email_content: str) -> List[Dict[str, Any]]:
    """
    Extract product information from email content.
    
    Args:
        email_content: The content of the email
        
    Returns:
        List of dictionaries containing product code and quantity
    """
    logger.info("Extracting product information from email content")
    products = []
    
    # Use regex to find product codes and quantities
    # Updated pattern to handle both xx-xx-xxxx and xxxxx-xxxx formats
    pattern = r'(\d+(?:-\d+)+),\s*(\d+)([Kk]?)pcs'
    matches = re.finditer(pattern, email_content)
    
    for match in matches:
        product_code = match.group(1)
        quantity = int(match.group(2))
        
        # Handle K/k suffix (thousands)
        if match.group(3).lower() == 'k':
            quantity *= 1000
            
        products.append({
            "product_code": product_code,
            "quantity": quantity
        })
        logger.info(f"Found product: {product_code}, quantity: {quantity}")
    
    logger.info(f"Extracted {len(products)} products from email")
    return products

@mcp.tool()
@update_docstring_with_info
def get_current_time(timezone_name: str) -> str:
    """Get current time in specified timezone
    
    Args:
        timezone_name: IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Use '{local_tz}' as local timezone if no timezone provided by the user."
    
    """
    logger.info(f"Getting current time for timezone: {timezone_name}")
    timezone = get_zoneinfo(timezone_name)
    current_time = datetime.now(timezone)
    
    result = json.dumps(dict(
        timezone=timezone_name,
        datetime=current_time.isoformat(timespec="seconds"),
        is_dst=bool(current_time.dst()),
    ),ensure_ascii=False)
    
    logger.info(f"Current time response: {result}")
    return result


@mcp.tool()
@update_docstring_with_info
def generate_quote(email_content: str) -> str:
    """
    Generate a price quote based on product information in an email.
    
    Args:
        email_content: The content of the email containing product codes and quantities
        
    Returns:
        A formatted quote with pricing information
    """
    logger.info("Generating price quote from email content")
    products = extract_product_info(email_content)
    
    if not products:
        logger.warning("No valid product information found in the email")
        return json.dumps({
            "error": "No valid product information found in the email",
            "quote": None
        })
    
    quote_items = []
    total_amount = 0
    currency = "USD"  # Default currency
    
    for product in products:
        product_code = product["product_code"]
        quantity = product["quantity"]
        
        if product_code in PRODUCT_PRICES:
            price_info = PRODUCT_PRICES[product_code]
            unit_price = price_info["unit_price"]
            currency = price_info["currency"]
            min_order = price_info["min_order"]
            
            # Apply discount for larger quantities
            if quantity >= min_order * 10:
                discount = 0.15  # 15% discount
                logger.info(f"Applied 15% discount for product {product_code} (quantity: {quantity})")
            elif quantity >= min_order * 5:
                discount = 0.10  # 10% discount
                logger.info(f"Applied 10% discount for product {product_code} (quantity: {quantity})")
            elif quantity >= min_order * 2:
                discount = 0.05  # 5% discount
                logger.info(f"Applied 5% discount for product {product_code} (quantity: {quantity})")
            else:
                discount = 0
                logger.info(f"No discount applied for product {product_code} (quantity: {quantity})")
                
            discounted_price = unit_price * (1 - discount)
            line_total = discounted_price * quantity
            total_amount += line_total
            
            quote_items.append({
                "product_code": product_code,
                "quantity": quantity,
                "unit_price": unit_price,
                "discount": f"{discount:.0%}" if discount > 0 else "None",
                "discounted_price": discounted_price,
                "line_total": line_total,
                "discount_value": discount  # Adding raw discount value for better formatting
            })
        else:
            logger.warning(f"Product not found in catalog: {product_code}")
            quote_items.append({
                "product_code": product_code,
                "quantity": quantity,
                "error": "Product not found in catalog"
            })
    
    # Generate quote with unique ID and validity period
    quote_date = datetime.now()
    valid_until = quote_date + timedelta(days=30)
    
    quote_id = f"Q-{quote_date.strftime('%Y%m%d')}-{hash(email_content) % 10000:04d}"
    logger.info(f"Generated quote ID: {quote_id}")
    
    quote = {
        "quote_id": quote_id,
        "date": quote_date.strftime("%Y-%m-%d"),
        "valid_until": valid_until.strftime("%Y-%m-%d"),
        "currency": currency,
        "items": quote_items,
        "total_amount": total_amount,
        "terms": "Payment terms: Net 30 days. Shipping not included."
    }
    
    logger.info(f"Quote generated successfully with {len(quote_items)} items, total amount: {total_amount} {currency}")
    return json.dumps(quote, indent=2)
    
    
if __name__ == "__main__":
    logger.info("Starting quote-server MCP server")
    mcp.run()
    # print(get_current_time("Asia/Shanghai"))
    