# GenAI Email Customer Service Assistant

This project implements an MCP (Model Context Protocol) server that processes customer emails and generates price quotes automatically.

## Features

- Extract product codes and quantities from customer emails
- Calculate pricing with appropriate volume discounts
- Generate formatted price quotes with unique IDs
- Provide current time information in specified timezones

## Setup and Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/genai-email-customer-service-assistant.git
   cd genai-email-customer-service-assistant
   ```

2. Set up a virtual environment:
   ```
   cd mcp_server
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Running the MCP Server

Start the server:
```
cd mcp_server
python server.py
```

## Usage

The MCP server provides two main tools:

1. `get_current_time`: Gets the current time in a specified timezone
2. `generate_quote`: Generates a price quote based on product information in an email

Example email format for price quotes:
```
Subject: RE: Check price

Hi LSCS Team,

Kindly check price below items:
Hope to hear from you by today
Thanks.

1) 08-50-0113, 20Kpcs
2) 22-01-1042, 5Kpcs
3) 42816-0212, 200pcs
```

## Discount Structure

The server applies volume discounts based on order quantity:
- 15% discount for quantities ≥ 10x minimum order
- 10% discount for quantities ≥ 5x minimum order
- 5% discount for quantities ≥ 2x minimum order

## License

[Your license information here]
