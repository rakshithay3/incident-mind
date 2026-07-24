import urllib.request
import json
import time
import random

GATEWAY_URL = "http://localhost:80"

products = ["Keychron", "Logitech", "Sony", "Dell", "Elgato", "iPad"]

def send_request(url, method="GET", data=None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body = json.dumps(data).encode("utf-8") if data else None
    try:
        with urllib.request.urlopen(req, data=body, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except Exception as e:
        return 500, str(e)

def run_load():
    print("Starting background load generator...")
    while True:
        try:
            # 1. Simulate Search
            query = random.choice(products)
            status, resp = send_request(f"{GATEWAY_URL}/api/search?q={query}")
            
            # 2. Simulate Order Checkout Flow
            order_data = {
                "userId": random.randint(1, 100),
                "items": [{"productId": "p1", "quantity": 1}],
                "paymentMethod": "razorpay"
            }
            status, resp_body = send_request(f"{GATEWAY_URL}/api/order/create", "POST", order_data)
            
            if status == 200:
                order_resp = json.loads(resp_body)
                payment_order_id = order_resp.get("paymentOrderId")
                
                # 3. Simulate Payment Verification
                if payment_order_id:
                    verify_data = {
                        "razorpay_order_id": payment_order_id,
                        "razorpay_payment_id": f"pay_{random.randint(1000, 9999)}",
                        "razorpay_signature": "signature_mock"
                    }
                    send_request(f"{GATEWAY_URL}/api/payment/verify-payment", "POST", verify_data)
            
        except Exception as e:
            print(f"Error in load iteration: {e}")
            
        # Run loop roughly every 500ms
        time.sleep(0.5)

if __name__ == "__main__":
    try:
        run_load()
    except KeyboardInterrupt:
        print("\nLoad generator stopped.")
