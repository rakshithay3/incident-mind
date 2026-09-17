import urllib.request
import json
import time
import random
import threading

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

def worker():
    # Stagger thread start slightly
    time.sleep(random.uniform(0, 0.5))
    while True:
        try:
            # 1. Simulate Search
            query = random.choice(products)
            send_request(f"{GATEWAY_URL}/api/search?q={query}")
            
            # 2. Simulate Order Checkout Flow
            order_data = {
                "userId": random.randint(1, 100),
                "items": [{"productId": "p1", "quantity": 1}],
                "paymentMethod": "razorpay"
            }
            status, resp_body = send_request(f"{GATEWAY_URL}/api/order/create", "POST", order_data)
            
            if status == 200:
                try:
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
                except Exception:
                    pass
            
            # 4. Simulate Auth Login (auth-service)
            auth_data = {"username": "admin", "password": "admin"}
            send_request(f"{GATEWAY_URL}/api/auth/login", "POST", auth_data)
            
            # 5. Simulate Fetching User Profile (user-service)
            send_request(f"{GATEWAY_URL}/api/user/1")
            
        except Exception as e:
            print(f"Error in load iteration: {e}")
            
        # Run loop roughly every 2.0s to maintain healthy concurrent load (~10 req/s)
        time.sleep(2.0)

def run_load():
    print("Starting background concurrent load generator (5 threads)...")
    threads = []
    for i in range(5):
        t = threading.Thread(target=worker, name=f"load-worker-{i}")
        t.daemon = True
        t.start()
        threads.append(t)
        
    while True:
        time.sleep(1)

if __name__ == "__main__":
    try:
        run_load()
    except KeyboardInterrupt:
        print("\nLoad generator stopped.")

