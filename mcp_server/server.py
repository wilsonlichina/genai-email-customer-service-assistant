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
    # Original products with dashed format
    "08-50-0113": {"unit_price": 1.25, "currency": "USD", "min_order": 1000},
    "22-01-1042": {"unit_price": 3.75, "currency": "USD", "min_order": 500},
    "42816-0212": {"unit_price": 15.50, "currency": "USD", "min_order": 100},
    
    # Add new product formats from emails
    "STM32G030K8T6": {"unit_price": 2.35, "currency": "USD", "min_order": 1000},
    "RY8601AT6": {"unit_price": 0.85, "currency": "USD", "min_order": 500},
    
    # Add capacitor products from email5
    "CC0402KRX7R9BB102": {"unit_price": 0.08, "currency": "USD", "min_order": 100},
    "CL05B102KB5NNNC": {"unit_price": 0.07, "currency": "USD", "min_order": 100},
    "CC0603KRX7R9BB473": {"unit_price": 0.10, "currency": "USD", "min_order": 100},
    "CL10B473KB8NNNC": {"unit_price": 0.09, "currency": "USD", "min_order": 100},
}

def extract_product_info(email_content: str, subject: str = "") -> List[Dict[str, Any]]:
    """
    Extract product information from email content and subject.
    
    Args:
        email_content: The content of the email
        subject: The subject of the email (optional)
        
    Returns:
        List of dictionaries containing product code and quantity
    """
    logger.info("Extracting product information from email content")
    products = []
    combined_text = subject + "\n" + email_content
    
    # Extract product codes - multiple formats
    # Look for different product code patterns
    product_code_patterns = [
        # Pattern 1: Standard format with dashes like 08-50-0113, 42816-0212
        r'(\d+(?:-\d+)+)',
        # Pattern 2: General alphanumeric product codes (most flexible)
        r'([A-Z]{2}[0-9]{2,6}[A-Z]+[0-9A-Z]*)',
        # Pattern 3: Specific format for microcontrollers like STM32G030K8T6
        r'([A-Z0-9]{5,}[A-Z][0-9A-Z]{3,})',
        # Pattern 4: Codes with mixed characters like CC0402KRX7R9BB102
        r'([A-Z]{2}[0-9]{4,}[A-Z0-9]{5,})', 
        # Pattern 5: Simple pattern for codes in "LETTERSNUMBERS" format
        r'\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]*)\b'
    ]
    
    # First, find all possible product codes
    product_codes = set()
    for pattern in product_code_patterns:
        matches = re.finditer(pattern, combined_text)
        for match in matches:
            code = match.group(1)
            # Skip common words/numbers that might be incorrectly matched
            if len(code) >= 6 and not code.lower() in ['pieces', 'thank', 'today']:
                product_codes.add(code)
    
    logger.info(f"Found potential product codes: {product_codes}")
    
    # Now extract quantities - multiple formats
    quantity_patterns = [
        # Format 1: 20Kpcs, 5Kpcs, 200pcs
        (r'(\d+)([Kk]?)pcs', lambda m: int(m.group(1)) * (1000 if m.group(2).lower() == 'k' else 1)),
        # Format 2: 10000 pieces, one shot collection for 10000 pieces
        (r'(\d+)\s*pieces', lambda m: int(m.group(1))),
        # Format 3: for 1000 and 5000 pcs
        (r'for\s+(\d+)\s+and\s+(\d+)\s+pcs', lambda m: [int(m.group(1)), int(m.group(2))]),
        # Format 4: for 10000 pcs
        (r'for\s+(\d+)\s+pcs', lambda m: int(m.group(1))),
        # Format 5: one shot collection for 10000
        (r'(?:one\s+shot|collection)\s+(?:for\s+)?(\d+)', lambda m: int(m.group(1))),
        # Format 6: Just numbers with K suffix
        (r'(\d+)[Kk]', lambda m: int(m.group(1)) * 1000)
    ]
    
    # For each product code, try to find associated quantities
    for code in product_codes:
        quantities = []
        # Check if any quantity patterns appear near this code (within 100 chars)
        code_pos = combined_text.find(code)
        if code_pos >= 0:
            search_area = combined_text[max(0, code_pos - 50):min(len(combined_text), code_pos + 100)]
            
            for pattern, extract_func in quantity_patterns:
                qty_matches = re.finditer(pattern, search_area)
                for qty_match in qty_matches:
                    qty_result = extract_func(qty_match)
                    if isinstance(qty_result, list):
                        quantities.extend(qty_result)
                    else:
                        quantities.append(qty_result)
        
        # If no quantity found but code is in subject, check for quantities in body
        if not quantities and subject and code in subject:
            for pattern, extract_func in quantity_patterns:
                qty_matches = re.finditer(pattern, email_content)
                for qty_match in qty_matches:
                    qty_result = extract_func(qty_match)
                    if isinstance(qty_result, list):
                        quantities.extend(qty_result)
                    else:
                        quantities.append(qty_result)
        
        # Look for standalone numbers near products when no quantity formats match
        if not quantities and code_pos >= 0:
            search_area = combined_text[max(0, code_pos - 50):min(len(combined_text), code_pos + 100)]
            standalone_numbers = re.findall(r'(?<![A-Za-z0-9-])(\d{3,})(?![A-Za-z0-9-])', search_area)
            
            for num_str in standalone_numbers:
                try:
                    num = int(num_str)
                    # Only consider reasonable quantities (between 10 and 1,000,000)
                    if 10 <= num <= 1000000:
                        quantities.append(num)
                        logger.info(f"Found standalone quantity for {code}: {num}")
                except ValueError:
                    continue
        
        # Default quantity if still none found
        if not quantities:
            # Use min order from product database if product exists there
            if code in PRODUCT_PRICES:
                default_qty = PRODUCT_PRICES[code]["min_order"]
                logger.info(f"No quantity found for product: {code}, using min order: {default_qty}")
                quantities = [default_qty]
            else:
                # Use general default for unknown products
                logger.info(f"No quantity found for product: {code}, using default of 1000")
                quantities = [1000]
        
        # Create product entries for each quantity
        for qty in quantities:
            products.append({
                "product_code": code,
                "quantity": qty
            })
            logger.info(f"Found product: {code}, quantity: {qty}")
    
    logger.info(f"Extracted {len(products)} product-quantity combinations from email")
    return products

# @mcp.tool()
# @update_docstring_with_info
# def get_current_time(timezone_name: str) -> str:
#     """Get current time in specified timezone
    
#     Args:
#         timezone_name: IANA timezone name (e.g., 'America/New_York', 'Europe/London'). Use '{local_tz}' as local timezone if no timezone provided by the user."
    
#     """
#     logger.info(f"Getting current time for timezone: {timezone_name}")
#     timezone = get_zoneinfo(timezone_name)
#     current_time = datetime.now(timezone)
    
#     result = json.dumps(dict(
#         timezone=timezone_name,
#         datetime=current_time.isoformat(timespec="seconds"),
#         is_dst=bool(current_time.dst()),
#     ),ensure_ascii=False)
    
#     logger.info(f"Current time response: {result}")
#     return result


# @mcp.tool()
# @update_docstring_with_info
# def generate_quote(email_content: str, subject: str = "") -> str:
#     """
#     Generate a price quote based on product information in an email.
    
#     Args:
#         email_content: The content of the email containing product codes and quantities
#         subject: The subject of the email (optional)
        
#     Returns:
#         A formatted quote with pricing information
#     """
#     logger.info("Generating price quote from email content")
#     products = extract_product_info(email_content, subject)
    
#     if not products:
#         logger.warning("No valid product information found in the email")
#         return json.dumps({
#             "error": "No valid product information found in the email",
#             "quote": None
#         })
    
#     quote_items = []
#     total_amount = 0
#     currency = "USD"  # Default currency
    
#     for product in products:
#         product_code = product["product_code"]
#         quantity = product["quantity"]
        
#         if product_code in PRODUCT_PRICES:
#             price_info = PRODUCT_PRICES[product_code]
#             unit_price = price_info["unit_price"]
#             currency = price_info["currency"]
#             min_order = price_info["min_order"]
            
#             # Apply discount for larger quantities
#             if quantity >= min_order * 10:
#                 discount = 0.15  # 15% discount
#                 logger.info(f"Applied 15% discount for product {product_code} (quantity: {quantity})")
#             elif quantity >= min_order * 5:
#                 discount = 0.10  # 10% discount
#                 logger.info(f"Applied 10% discount for product {product_code} (quantity: {quantity})")
#             elif quantity >= min_order * 2:
#                 discount = 0.05  # 5% discount
#                 logger.info(f"Applied 5% discount for product {product_code} (quantity: {quantity})")
#             else:
#                 discount = 0
#                 logger.info(f"No discount applied for product {product_code} (quantity: {quantity})")
                
#             discounted_price = unit_price * (1 - discount)
#             line_total = discounted_price * quantity
#             total_amount += line_total
            
#             quote_items.append({
#                 "product_code": product_code,
#                 "quantity": quantity,
#                 "unit_price": unit_price,
#                 "discount": f"{discount:.0%}" if discount > 0 else "None",
#                 "discounted_price": discounted_price,
#                 "line_total": line_total,
#                 "discount_value": discount  # Adding raw discount value for better formatting
#             })
#         else:
#             logger.warning(f"Product not found in catalog: {product_code}")
#             quote_items.append({
#                 "product_code": product_code,
#                 "quantity": quantity,
#                 "error": "Product not found in catalog"
#             })
    
#     # Generate quote with unique ID and validity period
#     quote_date = datetime.now()
#     valid_until = quote_date + timedelta(days=30)
    
#     quote_id = f"Q-{quote_date.strftime('%Y%m%d')}-{hash(email_content) % 10000:04d}"
#     logger.info(f"Generated quote ID: {quote_id}")
    
#     quote = {
#         "quote_id": quote_id,
#         "date": quote_date.strftime("%Y-%m-%d"),
#         "valid_until": valid_until.strftime("%Y-%m-%d"),
#         "currency": currency,
#         "items": quote_items,
#         "total_amount": total_amount,
#         "terms": "Payment terms: Net 30 days. Shipping not included."
#     }
    
#     logger.info(f"Quote generated successfully with {len(quote_items)} items, total amount: {total_amount} {currency}")
#     return json.dumps(quote, indent=2)


@mcp.tool()
@update_docstring_with_info
def generate_quote_by_product(product_code: str, quantity: int, brand: str="") -> str:
    """
    Generate a price quote for a specific product with given code,quantity and brand.
    
    Args:
        product_code: The product code to generate a quote for
        quantity: The quantity of the product
        brand: The brand of the product (optional)
        
    Returns:
        A formatted quote with pricing information
    """
    logger.info(f"Generating price quote for product: {product_code}, brand: {brand}, quantity: {quantity}")
    
    quote_items = []
    total_amount = 0
    currency = "USD"  # Default currency
    
    # Check if product exists in our database
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
        total_amount = line_total
        
        quote_items.append({
            "product_code": product_code,
            "brand": brand,
            "quantity": quantity,
            "unit_price": unit_price,
            "discount": f"{discount:.0%}" if discount > 0 else "None",
            "discounted_price": discounted_price,
            "line_total": line_total
        })
    else:
        logger.warning(f"Product not found in catalog: {product_code}")
        return json.dumps({
            "error": f"Product {product_code} not found in catalog",
            "quote": None
        })
    
    # Generate quote with unique ID and validity period
    quote_date = datetime.now()
    valid_until = quote_date + timedelta(days=30)
    
    # Generate a unique quote ID based on product code, brand, and quantity
    quote_id = f"Q-{quote_date.strftime('%Y%m%d')}-{hash(f'{product_code}{brand}{quantity}') % 10000:04d}"
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
    
    logger.info(f"Quote generated successfully for product {product_code}, total amount: {total_amount} {currency}")
    return json.dumps(quote, indent=2)
    
    
if __name__ == "__main__":
    logger.info("Starting quote-server MCP server")
    mcp.run()
    # print(get_current_time("Asia/Shanghai"))
