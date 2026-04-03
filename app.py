import os, json, cv2
from flask import Flask, render_template, request, redirect, session, flash, Response, url_for
from werkzeug.utils import secure_filename
import mysql.connector
from flask import send_from_directory
from ultralytics import YOLO

model = YOLO("yolov8n.pt")


app = Flask(__name__)
app.secret_key = "secure_key"

# ---------------- DATABASE ----------------
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="ecommerce_verify",
        charset="utf8"
    )

PRODUCT_UPLOAD = "static/uploads/products"
os.makedirs(PRODUCT_UPLOAD, exist_ok=True)

PRODUCT_UPLOAD = "static/uploads/products"
VIDEO_UPLOAD = "static/uploads/videos"
os.makedirs(PRODUCT_UPLOAD, exist_ok=True)
os.makedirs(VIDEO_UPLOAD, exist_ok=True)

# ---------------- GLOBAL STATS ----------------
stats = {
    "matched": 0,
    "mismatched": 0,
    "confidence": []
}

from datetime import datetime

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

@app.route("/")
def index():
    return render_template("index.html")

# ======================================================
# ADMIN LOGIN (NO REGISTER)
# ======================================================
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "admin":
            session["role"] = "admin"
            return redirect("/admin/dashboard")
        flash("Invalid admin credentials")
    return render_template("admin_login.html")

@app.route("/admin/dashboard")
def admin_dashboard():
    if session.get("role") != "admin":
        return redirect("/admin/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE status='pending'")
    users = cur.fetchall()
    return render_template("admin_dashboard.html", users=users)

@app.route("/admin/approve/<int:uid>")
def admin_approve(uid):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE users SET status='approved' WHERE id=%s", (uid,))
    db.commit()
    return redirect("/admin/dashboard")

@app.route("/admin/reject/<int:uid>")
def admin_reject(uid):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE users SET status='rejected' WHERE id=%s", (uid,))
    db.commit()
    return redirect("/admin/dashboard")

# ======================================================
# SELLER REGISTER & LOGIN
# ======================================================
@app.route("/seller/register", methods=["GET","POST"])
def seller_register():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO users
            (role, name, email, mobile, shop_name, shop_address, username, password)
            VALUES ('seller', %s,%s,%s,%s,%s,%s,%s)
        """, (
            request.form["name"],
            request.form["email"],
            request.form["mobile"],
            request.form["shop_name"],
            request.form["shop_address"],
            request.form["username"],
            request.form["password"]
        ))
        db.commit()
        flash("Seller registered. Wait for admin approval.")
        return redirect("/seller/login")
    return render_template("seller_register.html")

@app.route("/seller/login", methods=["GET","POST"])
def seller_login():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT * FROM users 
            WHERE role='seller' AND username=%s AND password=%s AND status='approved'
        """, (request.form["username"], request.form["password"]))
        user = cur.fetchone()
        if user:
            session["role"] = "seller"
            session["uid"] = user["id"]
            return redirect("/seller/dashboard")
        flash("Invalid or unapproved seller account")
    return render_template("seller_login.html")

@app.route("/seller/dashboard")
def seller_dashboard():
    if session.get("role") != "seller":
        return redirect("/seller/login")
    return render_template("seller_dashboard.html")

# ======================================================
# SELLER – ADD PRODUCT
# ======================================================
@app.route("/seller/add-product", methods=["GET", "POST"])
def seller_add_product():
    if session.get("role") != "seller":
        return redirect("/seller/login")

    if request.method == "POST":
        image = request.files["image"]
        filename = secure_filename(image.filename)
        image.save(os.path.join(PRODUCT_UPLOAD, filename))

        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO products (seller_id, name, image, specification, price, stock)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            session["uid"],
            request.form["name"],
            filename,
            request.form["specification"],
            request.form["price"],
            request.form["stock"]
        ))
        db.commit()
        return redirect("/seller/products")

    return render_template("seller_add_product.html")

# ======================================================
# SELLER – VIEW PRODUCTS
# ======================================================
@app.route("/seller/products")
def seller_products():
    if session.get("role") != "seller":
        return redirect("/seller/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM products WHERE seller_id=%s", (session["uid"],))
    products = cur.fetchall()

    return render_template("seller_products.html", products=products)

# ======================================================
# SELLER – VIEW ORDERS
# ======================================================
@app.route("/seller/orders")
def seller_orders():
    if session.get("role") != "seller":
        return redirect("/seller/login")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Seller orders
    cur.execute("""
        SELECT o.*, u.name AS customer_name
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        WHERE o.seller_id = %s
        ORDER BY o.created_at DESC
    """, (session["uid"],))
    orders = cur.fetchall()

    # Delivery partners
    cur.execute("""
        SELECT id, name 
        FROM users 
        WHERE role='delivery' AND status='approved'
    """)
    delivery_partners = cur.fetchall()

    return render_template(
        "seller_orders.html",
        orders=orders,
        delivery_partners=delivery_partners
    )

@app.route("/seller/assign-delivery/<int:order_id>", methods=["POST"])
def seller_assign_delivery(order_id):
    if session.get("role") != "seller":
        return redirect("/seller/login")

    delivery_id = request.form.get("delivery_id")
    if not delivery_id:
        flash("Please select a delivery partner")
        return redirect("/seller/orders")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET delivery_id=%s, status='Delivery Assigned'
        WHERE id=%s AND seller_id=%s
    """, (delivery_id, order_id, session["uid"]))
    db.commit()

    flash("Delivery partner assigned successfully")
    return redirect("/seller/orders")


# ======================================================
# SELLER – ACCEPT ORDER
# ======================================================
@app.route("/seller/order/accept/<int:order_id>", methods=["POST"])
def seller_accept_order(order_id):
    if session.get("role") != "seller":
        return redirect("/seller/login")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET status='Approved'
        WHERE id=%s AND seller_id=%s
    """, (order_id, session["uid"]))
    db.commit()

    return redirect("/seller/orders")

@app.route("/video/<filename>")
def serve_video(filename):
    return send_from_directory(
        VIDEO_UPLOAD,
        filename,
        mimetype="video/mp4"
    )

# ======================================================
# SELLER – REJECT ORDER
# ======================================================
@app.route("/seller/order/reject/<int:order_id>", methods=["GET","POST"])
def seller_reject_order(order_id):
    if session.get("role") != "seller":
        return redirect("/seller/login")

    reason = request.form.get("reason")
    if not reason:
        flash("Reason for rejection is mandatory")
        return redirect("/seller/orders")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET status='Rejected', seller_reject_reason=%s
        WHERE id=%s AND seller_id=%s
    """, (reason, order_id, session["uid"]))
    db.commit()

    return redirect("/seller/orders")

@app.route("/seller/upload-packing/<int:order_id>", methods=["GET", "POST"])
def upload_packing(order_id):
    if session.get("role") != "seller":
        return redirect("/seller/login")

    if request.method == "POST":
        video = request.files["packing_video"]
        filename = secure_filename(f"packing_{order_id}.mp4")
        path = os.path.join(VIDEO_UPLOAD, filename)
        video.save(path)

        # Save video path in orders table
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "UPDATE orders SET packing_video=%s WHERE id=%s AND seller_id=%s",
            (filename, order_id, session["uid"])
        )
        db.commit()

        # Redirect immediately to result page
        return redirect(url_for("packing_result", order_id=order_id))

    return render_template("seller_upload_packing.html", order_id=order_id)




from ultralytics import YOLO
import cv2
import os
from skimage.metrics import structural_similarity as ssim
import shutil

PACKING_DETECT_DIR = "static/detections/packing"

import cv2
import os
from imutils import build_montages
from pathlib import Path

DETECTIONS_DIR = "static/detections/packing"

def analyze_unique_objects(video_path, order_id):
    """
    Process video frame by frame and save only unique objects.
    """
    cap = cv2.VideoCapture(video_path)
    save_dir = os.path.join(DETECTIONS_DIR, f"order_{order_id}")
    os.makedirs(save_dir, exist_ok=True)

    saved_crops = []  # grayscale arrays for similarity
    saved_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results = model(frame)[0]

        for box, cls in zip(results.boxes.xyxy.tolist(), results.boxes.cls.tolist()):
            if int(cls) == 0:  # skip person
                continue

            x1, y1, x2, y2 = map(int, box)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            # Resize and grayscale for similarity comparison
            crop_gray = cv2.cvtColor(cv2.resize(crop, (50, 50)), cv2.COLOR_BGR2GRAY)

            # Compare with all previously saved crops
            is_unique = True
            for saved in saved_crops:
                if ssim(crop_gray, saved) > 0.95:  # very similar
                    is_unique = False
                    break

            if is_unique:
                saved_count += 1
                img_name = f"detected_{saved_count}.jpg"
                cv2.imwrite(os.path.join(save_dir, img_name), crop)
                saved_crops.append(crop_gray)

    cap.release()
    return sorted(os.listdir(save_dir))  # list of unique images

@app.route("/seller/get-detected/<int:order_id>")
def get_detected_images(order_id):
    order_dir = os.path.join(DETECTIONS_DIR, f"order_{order_id}")
    images = []
    if os.path.exists(order_dir):
        images = sorted(os.listdir(order_dir))
    return {"images": images}

def yolo_detect(frame, save_dir, frame_no):
    """
    Detect objects using YOLOv8n, ignore 'person', save cropped objects
    """
    results = yolo(frame, conf=0.4, verbose=False)  # detect objects

    for r in results:
        for i, box in enumerate(r.boxes):
            cls = int(box.cls[0])  # class index
            if cls == 0:  # 0 = person
                continue  # skip people

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            crop = frame[y1:y2, x1:x2]

            if crop.size == 0:
                continue

            # Save cropped object (no label)
            filename = f"{frame_no}_{i}.jpg"
            cv2.imwrite(os.path.join(save_dir, filename), crop)

            # Draw green box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

    return frame



def stream_packing_yolo(video_path, order_id):
    cap = cv2.VideoCapture(video_path)

    save_dir = f"static/detections/packing/order_{order_id}"
    os.makedirs(save_dir, exist_ok=True)

    frame_no = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = yolo_detect(frame, save_dir, frame_no)

        _, buffer = cv2.imencode(".jpg", frame)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" +
            buffer.tobytes() + b"\r\n"
        )

        frame_no += 1

    cap.release()
@app.route("/seller/packing-result/<int:order_id>")
def packing_result(order_id):
    save_dir = os.path.join(DETECTIONS_DIR, f"order_{order_id}")
    os.makedirs(save_dir, exist_ok=True)

    detected_images = sorted(os.listdir(save_dir))  # unique images saved during streaming

    return render_template("seller_packing_result.html",
                           order_id=order_id,
                           detected_images=detected_images)


from flask import Response, send_from_directory
import cv2

@app.route("/seller/packing-feed/<int:order_id>")
def seller_packing_feed(order_id):
    video_path = os.path.join(VIDEO_UPLOAD, f"packing_{order_id}.mp4")
    return Response(generate_frames(video_path, order_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')



DETECTIONS_DIR = "static/detections/packing"

from skimage.metrics import structural_similarity as ssim
import cv2
import os
def iou(boxA, boxB):
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])

    return interArea / float(boxAArea + boxBArea - interArea + 1e-5)


def generate_frames(video_path, order_id):
    cap = cv2.VideoCapture(video_path)
    save_dir = os.path.join(DETECTIONS_DIR, f"order_{order_id}")
    os.makedirs(save_dir, exist_ok=True)

    detected_objects = []  
    # each item → {"crop": gray_img, "box": (x1,y1,x2,y2)}

    saved_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results = model(frame)[0]

        for box, cls in zip(results.boxes.xyxy.tolist(),
                            results.boxes.cls.tolist()):

            if int(cls) == 0:  # skip person
                continue

            x1, y1, x2, y2 = map(int, box)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            gray = cv2.cvtColor(
                cv2.resize(crop, (64, 64)),
                cv2.COLOR_BGR2GRAY
            )

            is_new = True

            for obj in detected_objects:
                similarity = ssim(gray, obj["crop"])
                overlap = iou((x1,y1,x2,y2), obj["box"])

                # SAME OBJECT → skip saving
                if similarity > 0.97 or overlap > 0.6:
                    is_new = False
                    break

            if is_new:
                saved_count += 1
                filename = f"detected_{saved_count}.jpg"
                cv2.imwrite(os.path.join(save_dir, filename), crop)

                detected_objects.append({
                    "crop": gray,
                    "box": (x1,y1,x2,y2)
                })

            # Draw detection box
            cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,0), 2)

        _, buffer = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" +
               buffer.tobytes() + b"\r\n")

    cap.release()

# ======================================================
# SELLER – VIEW DELIVERY PARTNERS
# ======================================================
@app.route("/seller/delivery-partners")
def seller_delivery_partners():
    if session.get("role") != "seller":
        return redirect("/seller/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT * FROM users 
        WHERE role='delivery' AND status='approved'
    """)
    partners = cur.fetchall()

    return render_template("seller_delivery_partners.html", partners=partners)

# ======================================================
# SELLER – ORDER HISTORY
# ======================================================
@app.route("/seller/order-history")
def seller_order_history():
    if session.get("role") != "seller":
        return redirect("/seller/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT * FROM orders 
        WHERE seller_id=%s AND status IN 
        ('Delivered','Rejected','Returned')
        ORDER BY created_at DESC
    """, (session["uid"],))
    history = cur.fetchall()

    return render_template("seller_order_history.html", orders=history)

# ======================================================
# SELLER – TRACK ORDER
# ======================================================
@app.route("/seller/track/<int:order_id>")
def seller_track_order(order_id):
    if session.get("role") != "seller":
        return redirect("/seller/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    order = cur.fetchone()

    return render_template("seller_track_order.html", order=order)

# ======================================================
# CUSTOMER REGISTER & LOGIN
# ======================================================
@app.route("/customer/register", methods=["GET","POST"])
def customer_register():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO users
            (role, name, email, mobile, address, username, password, status)
            VALUES ('customer', %s,%s,%s,%s,%s,%s,'approved')
        """, (
            request.form["name"],
            request.form["email"],
            request.form["mobile"],
            request.form["address"],
            request.form["username"],
            request.form["password"]
        ))
        db.commit()
        flash("Customer registered successfully")
        return redirect("/customer/login")
    return render_template("customer_register.html")

@app.route("/customer/login", methods=["GET","POST"])
def customer_login():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT * FROM users 
            WHERE role='customer' AND username=%s AND password=%s
        """, (request.form["username"], request.form["password"]))
        user = cur.fetchone()
        if user:
            session["role"] = "customer"
            session["uid"] = user["id"]
            return redirect("/customer/dashboard")
        flash("Invalid customer credentials")
    return render_template("customer_login.html")

@app.route("/customer/dashboard")
def customer_dashboard():
    if session.get("role") != "customer":
        return redirect("/customer/login")
    return render_template("customer_dashboard.html")

# ======================================================
# CUSTOMER – VIEW PRODUCTS
# ======================================================
@app.route("/customer/products")
def customer_products():
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT p.*, u.shop_name 
        FROM products p
        JOIN users u ON p.seller_id = u.id
    """)
    products = cur.fetchall()

    return render_template("customer_products.html", products=products)

# ======================================================
# CUSTOMER – PRODUCT DETAILS
# ======================================================
@app.route("/customer/product/<int:pid>")
def customer_product_detail(pid):
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT p.*, u.shop_name 
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.id=%s
    """, (pid,))
    product = cur.fetchone()

    return render_template("customer_product_detail.html", product=product)

# ======================================================
# CUSTOMER – ADD TO CART
# ======================================================
@app.route("/customer/add-to-cart/<int:pid>")
def customer_add_to_cart(pid):
    if session.get("role") != "customer":
        return redirect("/customer/login")

    cart = session.get("cart", {})

    cart[str(pid)] = cart.get(str(pid), 0) + 1
    session["cart"] = cart

    return redirect("/customer/cart")

# ======================================================
# CUSTOMER – VIEW CART
# ======================================================
@app.route("/customer/cart")
def customer_cart():
    if session.get("role") != "customer":
        return redirect("/customer/login")

    cart = session.get("cart", {})
    if not cart:
        return render_template("customer_cart.html", items=[], total=0)

    db = get_db()
    cur = db.cursor(dictionary=True)

    items = []
    total = 0

    for pid, qty in cart.items():
        cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
        product = cur.fetchone()
        if product:
            product["qty"] = qty
            product["subtotal"] = qty * float(product["price"])
            total += product["subtotal"]
            items.append(product)

    return render_template("customer_cart.html", items=items, total=total)

# ======================================================
# CUSTOMER – PLACE ORDER
# ======================================================
@app.route("/customer/place-order", methods=["POST"])
def customer_place_order():
    if session.get("role") != "customer":
        return redirect("/customer/login")

    cart = session.get("cart", {})
    if not cart:
        return redirect("/customer/cart")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Get seller from first product (single-seller assumption)
    first_pid = list(cart.keys())[0]
    cur.execute("SELECT seller_id FROM products WHERE id=%s", (first_pid,))
    seller_id = cur.fetchone()["seller_id"]

    # Create order
    cur.execute("""
        INSERT INTO orders (customer_id, seller_id, status)
        VALUES (%s,%s,'Order Placed')
    """, (session["uid"], seller_id))
    order_id = cur.lastrowid

    # Insert order items
    for pid, qty in cart.items():
        cur.execute("""
            INSERT INTO order_items (order_id, product_id, quantity)
            VALUES (%s,%s,%s)
        """, (order_id, pid, qty))

        cur.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (qty, pid))

    db.commit()
    session.pop("cart", None)

    return redirect("/customer/orders")

# ======================================================
# CUSTOMER – VIEW ORDERS
# ======================================================
@app.route("/customer/orders")
def customer_orders():
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT o.*, u.shop_name 
        FROM orders o
        JOIN users u ON o.seller_id = u.id
        WHERE o.customer_id=%s
        ORDER BY o.created_at DESC
    """, (session["uid"],))
    orders = cur.fetchall()

    return render_template("customer_orders.html", orders=orders)

# ======================================================
# CUSTOMER – ORDER DETAILS / TRACK
# ======================================================
@app.route("/customer/order/<int:oid>")
def customer_order_detail(oid):
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT * FROM orders WHERE id=%s AND customer_id=%s",
                (oid, session["uid"]))
    order = cur.fetchone()

    cur.execute("""
        SELECT p.name, oi.quantity, p.price
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id=%s
    """, (oid,))
    items = cur.fetchall()

    return render_template(
        "customer_order_detail.html",
        order=order,
        items=items
    )

# ======================================================
# CUSTOMER – ORDER HISTORY
# ======================================================
@app.route("/customer/order-history")
def customer_order_history():
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Fetch all customer orders
    cur.execute("""
        SELECT *
        FROM orders
        WHERE customer_id=%s
        ORDER BY created_at DESC
    """, (session["uid"],))
    orders = cur.fetchall()

    # Fetch items for each order
    for o in orders:
        cur.execute("""
            SELECT 
                p.name,
                p.price,
                oi.quantity
            FROM order_items oi
            JOIN products p ON p.id = oi.product_id
            WHERE oi.order_id = %s
        """, (o["id"],))
        o["items"] = cur.fetchall()  # IMPORTANT

    cur.close()
    db.close()

    return render_template(
        "customer_order_history.html",
        orders=orders
    )



@app.route("/customer/apply-return/<int:order_id>")
def apply_return(order_id):
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor()

    cur.execute("""
        UPDATE orders
        SET status='Returned',
            return_status='Pending'
        WHERE id=%s AND customer_id=%s AND status='Delivered'
    """, (order_id, session["uid"]))

    db.commit()
    cur.close()
    db.close()

    flash("Return request applied successfully.", "info")
    return redirect(url_for("customer_order_history"))


verify_cache = {}

# ======================================================
# CUSTOMER – VERIFY ORDER VIDEOS
# ======================================================
@app.route("/customer/verify/<int:order_id>")
def customer_verify(order_id):
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT packing_video, delivery_video
        FROM orders
        WHERE id=%s AND customer_id=%s
    """, (order_id, session["uid"]))
    order = cur.fetchone()

    if not order:
        flash("Order not found")
        return redirect("/customer/orders")

    packing_path = os.path.join(VIDEO_UPLOAD, order["packing_video"])
    delivery_path = os.path.join(VIDEO_UPLOAD, order["delivery_video"])

    packed = analyze_video_unique(packing_path)
    delivered = analyze_video_unique(delivery_path)

    matched, mismatched, confidence = compare_objects(packed, delivered)

    verify_cache[order_id] = {
        "matched": matched,
        "mismatched": mismatched,
        "confidence": confidence
    }

    return render_template("customer_verify.html", order_id=order_id)



# ======================================================
# STREAMING VIDEO FEEDS
# ======================================================
@app.route("/packing_feed/<int:order_id>")
def packing_feed(order_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT packing_video FROM orders WHERE id=%s", (order_id,))
    row = cur.fetchone()

    return Response(
        stream_video(os.path.join(VIDEO_UPLOAD, row["packing_video"])),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/delivery_feed/<int:order_id>")
def delivery_feed(order_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT delivery_video FROM orders WHERE id=%s", (order_id,))
    row = cur.fetchone()

    return Response(
        stream_video(os.path.join(VIDEO_UPLOAD, row["delivery_video"])),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

# ======================================================
# OBJECT DETECTION (FIXED)
# ======================================================
def detect_objects(frame):
    """
    Detect objects in a frame using contour area.
    Returns a list of tuples: (x, y, w, h, area)
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 60, 160)

    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    objects = []

    for c in cnts:
        area = cv2.contourArea(c)
        if area > 3500:  # only large enough contours
            x, y, w, h = cv2.boundingRect(c)
            objects.append((x, y, w, h, area))

    return objects  # always return list of 5-tuples

# ======================================================
# PACKING ANALYSIS (SAFE LOOP)
# ======================================================
def analyze_packing(video):
    cap = cv2.VideoCapture(video)
    unique_products = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        objects = detect_objects(frame)
        if not objects:
            continue  # skip frame if no objects

        for obj in objects:
            if not isinstance(obj, (list, tuple)) or len(obj) != 5:
                continue  # skip invalid detections
            _, _, _, _, area = obj
            if not any(abs(area - p) < 2000 for p in unique_products):
                unique_products.append(area)

    cap.release()

    # Save analyzed packing data
    json_file = video.replace(".mp4", "_objects.json")
    with open(json_file, "w") as f:
        json.dump(unique_products, f)


import cv2
import math

def analyze_video_unique(video):
    cap = cv2.VideoCapture(video)
    unique = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        for area in detect_objects(frame):
            # Check if this area is "new" compared to unique areas
            is_new = True
            for u in unique:
                # Euclidean distance between tuples
                distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(area, u)))
                if distance < 2000:  # threshold
                    is_new = False
                    break
            if is_new:
                unique.append(area)

    cap.release()
    return unique


import math

def compare_objects(packed, delivered):
    matched = []
    mismatched = []
    confidence = []

    for p, d in zip(packed, delivered):
        # Calculate Euclidean distance between tuples
        diff = math.sqrt(sum((a - b) ** 2 for a, b in zip(p, d)))
        
        # You can set a threshold to decide if they match
        if diff < 2000:  # adjust threshold as needed
            matched.append(p)
            confidence.append(max(0, 100 - diff/20))  # example confidence
        else:
            mismatched.append((p, d))
            confidence.append(max(0, 100 - diff/20))  # example confidence

    return matched, mismatched, confidence


def stream_video(video):
    cap = cv2.VideoCapture(video)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        for area in detect_objects(frame):
            pass  # draw optional boxes if needed

        _, buf = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\nContent-Type:image/jpeg\r\n\r\n" +
               buf.tobytes() + b"\r\n")

    cap.release()

# ======================================================
# STREAMING FUNCTIONS
# ======================================================
def stream_packing(video):
    cap = cv2.VideoCapture(video)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        for x, y, w, h, _ in detect_objects(frame):
            cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 200, 0), 2)

        _, buf = cv2.imencode(".jpg", frame)
        yield (b"--frame\r\nContent-Type:image/jpeg\r\n\r\n" +
               buf.tobytes() + b"\r\n")

    cap.release()


def stream_delivery(packing_video, delivery_video):
    global stats

    # Load reference objects from DELIVERY (packing) video
    with open(packing_video.replace(".mp4", "_objects.json")) as f:
        packed = json.load(f)   # list of tuples like (x, y, w, h, area)

    matched_ids = set()
    cap = cv2.VideoCapture(delivery_video)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        for x, y, w, h, area in detect_objects(frame):

            best_idx = -1
            best_diff = float("inf")

            for i, p in enumerate(packed):
                if i in matched_ids:
                    continue

                # ✅ FIX: Proper tuple distance (Euclidean)
                diff = ((area - p) ** 2) if isinstance(area, (int, float)) else \
                       (sum((a - b) ** 2 for a, b in zip(area, p))) ** 0.5

                if diff < best_diff:
                    best_diff = diff
                    best_idx = i

            if best_diff < 2500 and best_idx not in matched_ids:
                matched_ids.add(best_idx)
                stats["matched"] += 1
                conf = max(0, 100 - (best_diff / 50))
                stats["confidence"].append(conf)
                color, label = (0, 255, 0), "MATCH"
            else:
                stats["mismatched"] += 1
                color, label = (0, 0, 255), "MISMATCH"

            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 3)
            cv2.putText(
                frame, label, (x, y - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
            )

        _, buf = cv2.imencode(".jpg", frame)
        yield (
            b"--frame\r\nContent-Type:image/jpeg\r\n\r\n"
            + buf.tobytes()
            + b"\r\n"
        )

    cap.release()



# ======================================================
# RESULT PAGE
# ======================================================
@app.route("/customer/result/<int:order_id>")
def customer_result(order_id):
    result = verify_cache.get(order_id)

    if not result:
        flash("Verification not completed")
        return redirect("/customer/orders")

    matched = result["matched"]          # list of matched items
    mismatched = result["mismatched"]    # list of mismatched items

    total_count = len(matched) + len(mismatched)           # total number of items
    accuracy = round((len(matched) / total_count) * 100, 2) if total_count else 0

    avg_conf = round(sum(result["confidence"]) / len(result["confidence"]), 2) \
        if result["confidence"] else 0

    verdict = "accept" if len(matched) >= len(mismatched) else "reject"

    return render_template(
        "customer_result.html",
        order_id=order_id,
        matched=len(matched),
        mismatched=len(mismatched),
        accuracy=accuracy,
        confidence=avg_conf,
        verdict=verdict
    )


@app.route("/customer/accept/<int:order_id>")
def accept_order(order_id):
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        UPDATE orders
        SET status = %s
        WHERE id = %s AND customer_id = %s
        """,
        ("Delivered", order_id, session["uid"])
    )

    db.commit()
    cur.close()
    db.close()

    flash("Order accepted. Delivery verified successfully.", "success")
    return redirect(url_for("customer_orders"))

@app.route("/customer/reject/<int:order_id>")
def reject_order(order_id):
    if session.get("role") != "customer":
        return redirect("/customer/login")

    db = get_db()
    cur = db.cursor()

    cur.execute(
        """
        UPDATE orders
        SET status = %s,
            delivery_reject_reason = %s
        WHERE id = %s AND customer_id = %s
        """,
        (
            "Rejected",
            order_id,
            session["uid"]
        )
    )

    db.commit()
    cur.close()
    db.close()

    flash("Order rejected due to product mismatch.", "danger")
    return redirect(url_for("customer_orders"))


# ======================================================
# DELIVERY REGISTER & LOGIN
# ======================================================
@app.route("/delivery/register", methods=["GET","POST"])
def delivery_register():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO users
            (role, name, email, mobile, age, gender, licence_no, aadhar_no, username, password)
            VALUES ('delivery', %s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            request.form["name"],
            request.form["email"],
            request.form["mobile"],
            request.form["age"],
            request.form["gender"],
            request.form["licence_no"],
            request.form["aadhar_no"],
            request.form["username"],
            request.form["password"]
        ))
        db.commit()
        flash("Delivery partner registered. Wait for admin approval.")
        return redirect("/delivery/login")
    return render_template("delivery_register.html")

@app.route("/delivery/login", methods=["GET","POST"])
def delivery_login():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT * FROM users 
            WHERE role='delivery' AND username=%s AND password=%s AND status='approved'
        """, (request.form["username"], request.form["password"]))
        user = cur.fetchone()
        if user:
            session["role"] = "delivery"
            session["uid"] = user["id"]
            return redirect("/delivery/dashboard")
        flash("Invalid or unapproved delivery account")
    return render_template("delivery_login.html")

@app.route("/delivery/dashboard")
def delivery_dashboard():
    if session.get("role") != "delivery":
        return redirect("/delivery/login")
    return render_template("delivery_dashboard.html")

# ======================================================
# DELIVERY – VIEW ASSIGNED ORDERS
# ======================================================
@app.route("/delivery/orders")
def delivery_orders():
    if session.get("role") != "delivery":
        return redirect("/delivery/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT o.*, u.name AS customer_name, u.mobile AS customer_mobile, u.address AS customer_address
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        WHERE o.delivery_id=%s 
          AND o.status IN ('Delivery Assigned', 'Out for Delivery')
        ORDER BY o.created_at DESC
    """, (session["uid"],))
    orders = cur.fetchall()

    return render_template("delivery_orders.html", orders=orders)



# ======================================================
# DELIVERY – ORDER DETAIL
# ======================================================
@app.route("/delivery/order/<int:oid>")
def delivery_order_detail(oid):
    if session.get("role") != "delivery":
        return redirect("/delivery/login")

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Get order
    cur.execute("SELECT * FROM orders WHERE id=%s AND delivery_id=%s", (oid, session["uid"]))
    order = cur.fetchone()

    # Get items
    cur.execute("""
        SELECT p.name, oi.quantity, p.price
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id=%s
    """, (oid,))
    items = cur.fetchall()

    # Get customer info
    cur.execute("""
        SELECT name, mobile, address FROM users 
        WHERE id=(SELECT customer_id FROM orders WHERE id=%s)
    """, (oid,))
    customer = cur.fetchone()

    return render_template("delivery_order_detail.html",
                           order=order, items=items, customer=customer)

# ======================================================
# DELIVERY – ACCEPT DELIVERY
# ======================================================
@app.route("/delivery/accept/<int:oid>", methods=["POST"])
def delivery_accept(oid):
    if session.get("role") != "delivery":
        return redirect("/delivery/login")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET status='Out for Delivery'
        WHERE id=%s AND delivery_id=%s
    """, (oid, session["uid"]))
    db.commit()

    return redirect("/delivery/orders")

# ======================================================
# DELIVERY – REJECT DELIVERY
# ======================================================
@app.route("/delivery/reject/<int:oid>", methods=["POST"])
def delivery_reject(oid):
    if session.get("role") != "delivery":
        return redirect("/delivery/login")

    reason = request.form.get("reason")
    if not reason:
        flash("Reason for rejection is mandatory")
        return redirect(f"/delivery/order/{oid}")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET status='Delivery Rejected', delivery_reject_reason=%s
        WHERE id=%s AND delivery_id=%s
    """, (reason, oid, session["uid"]))
    db.commit()

    return redirect("/delivery/orders")

@app.route("/delivery/upload-delivery/<int:order_id>", methods=["GET", "POST"])
def upload_delivery(order_id):
    if session.get("role") != "delivery":
        return redirect("/delivery/login")

    if request.method == "POST":
        video = request.files["delivery_video"]
        filename = secure_filename(f"delivery_{order_id}.mp4")
        path = os.path.join(VIDEO_UPLOAD, filename)
        video.save(path)

        db = get_db()
        cur = db.cursor()
        cur.execute("""
            UPDATE orders 
            SET delivery_video=%s 
            WHERE id=%s AND delivery_id=%s
        """, (filename, order_id, session["uid"]))
        db.commit()

        flash("Delivery video uploaded successfully.")
        return redirect(url_for("delivery_verification", order_id=order_id))

    return render_template("delivery_upload.html", order_id=order_id)

DELIVERY_DETECT_DIR = "static/detections/delivery"

@app.route("/delivery/stream/<int:order_id>")
def delivery_stream(order_id):
    video_path = os.path.join(VIDEO_UPLOAD, f"delivery_{order_id}.mp4")
    return Response(
        generate_delivery_frames(video_path, order_id),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


from skimage.metrics import structural_similarity as ssim
import cv2, os

DELIVERY_DETECT_DIR = "static/detections/delivery"

def generate_delivery_frames(video_path, order_id):
    cap = cv2.VideoCapture(video_path)
    save_dir = os.path.join(DELIVERY_DETECT_DIR, f"order_{order_id}")
    os.makedirs(save_dir, exist_ok=True)

    detected_objects = []  
    # each → {"crop": gray_img, "box": (x1,y1,x2,y2)}

    saved_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results = model(frame)[0]

        for box, cls in zip(results.boxes.xyxy.tolist(),
                            results.boxes.cls.tolist()):

            # 🚫 COMPLETELY IGNORE PERSON CLASS
            if int(cls) == 0:
                continue

            x1, y1, x2, y2 = map(int, box)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            gray = cv2.cvtColor(
                cv2.resize(crop, (64, 64)),
                cv2.COLOR_BGR2GRAY
            )

            is_unique = True

            for obj in detected_objects:
                sim = ssim(gray, obj["crop"])
                overlap = iou((x1,y1,x2,y2), obj["box"])

                # SAME OBJECT → skip
                if sim > 0.97 or overlap > 0.6:
                    is_unique = False
                    break

            if is_unique:
                saved_count += 1
                cv2.imwrite(
                    os.path.join(save_dir, f"detected_{saved_count}.jpg"),
                    crop
                )

                detected_objects.append({
                    "crop": gray,
                    "box": (x1,y1,x2,y2)
                })

            # ✅ Draw box ONLY for non-person objects
            cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,0), 2)

        _, buffer = cv2.imencode(".jpg", frame)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" +
            buffer.tobytes() + b"\r\n"
        )

    cap.release()


@app.route("/delivery/get-detected/<int:order_id>")
def get_delivery_detected(order_id):
    order_dir = os.path.join(DELIVERY_DETECT_DIR, f"order_{order_id}")
    images = []
    if os.path.exists(order_dir):
        images = sorted(os.listdir(order_dir))
    return {"images": images}

@app.route("/delivery/verification/<int:order_id>")
def delivery_verification(order_id):
    return render_template("delivery_verification.html", order_id=order_id)



@app.route("/return/register", methods=["GET", "POST"])
def return_register():
    if request.method == "POST": 
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            INSERT INTO users
            (role, name, email, mobile, address, username, password, status)
            VALUES ('return', %s,%s,%s,%s,%s,%s,'pending')
        """, (
            request.form["name"],
            request.form["email"],
            request.form["mobile"],
            request.form["address"],
            request.form["username"],
            request.form["password"]
        ))
        db.commit()
        flash("Return team registered. Wait for admin approval.")
        return redirect("/return/login")
    return render_template("return_register.html")

@app.route("/return/login", methods=["GET", "POST"])
def return_login():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("""
            SELECT * FROM users
            WHERE role='return'
              AND username=%s
              AND password=%s
              AND status='approved'
        """, (request.form["username"], request.form["password"]))
        user = cur.fetchone()
        if user:
            session["role"] = "return"
            session["uid"] = user["id"]
            return redirect("/return/dashboard")
        flash("Invalid or unapproved return account")
    return render_template("return_login.html")

# ======================================================
# RETURN DASHBOARD
# ======================================================
@app.route("/return/dashboard")
def return_dashboard():
    if session.get("role") != "return":
        return redirect("/return/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT o.*, u.name AS customer_name
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        WHERE o.status='Returned'
        ORDER BY o.created_at DESC
    """)
    orders = cur.fetchall()
    cur.close()
    db.close()
    
    return render_template("return_dashboard.html", orders=orders)


# ======================================================
# RETURN ORDER DETAIL
# ======================================================
@app.route("/return/order/<int:order_id>")
def return_order_detail(order_id):
    if session.get("role") != "return":
        return redirect("/return/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    order = cur.fetchone()
    cur.close()
    db.close()

    if not order:
        flash("Order not found", "danger")
        return redirect("/return/dashboard")

    return render_template("return_order_detail.html", order=order)


# ======================================================
# UPLOAD RETURN VIDEO
# ======================================================
@app.route("/return/upload/<int:order_id>", methods=["GET", "POST"])
def upload_return_video(order_id):
    if session.get("role") != "return":
        return redirect("/return/login")

    if request.method == "POST":
        video = request.files.get("return_video")
        if not video:
            flash("No video uploaded.", "danger")
            return redirect(request.url)

        filename = secure_filename(f"return_{order_id}.mp4")
        path = os.path.join(VIDEO_UPLOAD, filename)
        video.save(path)

        db = get_db()
        cur = db.cursor()
        cur.execute("""
            UPDATE orders
            SET return_video=%s, return_status='Pending'
            WHERE id=%s
        """, (filename, order_id))
        db.commit()
        cur.close()
        db.close()

        flash("Return video uploaded successfully.", "success")
        return redirect(url_for("return_verify", order_id=order_id))

    return render_template("return_upload.html", order_id=order_id)

stats = {"matched": 0, "mismatched": 0, "confidence": []}

# ======================================================
# RETURN VERIFY PAGE
# ======================================================
@app.route("/return/verify/<int:order_id>")
def return_verify(order_id):
    if session.get("role") != "return":
        return redirect("/return/login")

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT delivery_video, return_video FROM orders WHERE id=%s", (order_id,))
    order = cur.fetchone()
    cur.close()
    db.close()

    if not order or not order["delivery_video"] or not order["return_video"]:
        flash("Delivery or return video missing.", "danger")
        return redirect("/return/dashboard")

    # ✅ Reset stats properly
    stats["matched"] = 0
    stats["mismatched"] = 0
    stats["confidence"] = []

    # ✅ Analyze DELIVERY video once (REFERENCE VIDEO)
    delivery_path = os.path.join(VIDEO_UPLOAD, order["delivery_video"])
    analyze_packing(delivery_path)   # This must create delivery_objects.json

    return render_template("return_verify.html", order_id=order_id)


# ======================================================
# STREAM DELIVERY VIDEO (JUST FOR DISPLAY)
# ======================================================
@app.route("/return/delivery_feed/<int:order_id>")
def return_delivery_feed(order_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT delivery_video FROM orders WHERE id=%s", (order_id,))
    row = cur.fetchone()
    cur.close()
    db.close()

    if not row or not row["delivery_video"]:
        flash("Delivery video missing.", "danger")
        return redirect("/return/dashboard")

    video_path = os.path.join(VIDEO_UPLOAD, row["delivery_video"])

    return Response(
        stream_packing(video_path),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# ======================================================
# STREAM RETURN VIDEO + COMPARE WITH DELIVERY
# ======================================================
@app.route("/return/verify_feed/<int:order_id>")
def return_verify_feed(order_id):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT delivery_video, return_video FROM orders WHERE id=%s", (order_id,))
    row = cur.fetchone()
    cur.close()
    db.close()

    if not row or not row["delivery_video"] or not row["return_video"]:
        flash("Videos missing.", "danger")
        return redirect("/return/dashboard")

    delivery_path = os.path.join(VIDEO_UPLOAD, row["delivery_video"])
    return_path = os.path.join(VIDEO_UPLOAD, row["return_video"])

    # ✅ IMPORTANT: delivery = reference, return = test
    return Response(
        stream_delivery(delivery_path, return_path),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# ======================================================
# RETURN RESULT PAGE
# ======================================================
@app.route("/return/result/<int:order_id>")
def return_result(order_id):
    matched = stats["matched"]
    mismatched = stats["mismatched"]
    total = matched + mismatched

    accuracy = round((matched / total) * 100, 2) if total else 0
    avg_conf = round(
        sum(stats["confidence"]) / len(stats["confidence"]), 2
    ) if stats["confidence"] else 0

    if mismatched > matched:
        verdict = "Rejected"
        message = "Returned product does not match delivered item."
        status = "Rejected"
    else:
        verdict = "Accepted"
        message = "Returned product matches delivered item."
        status = "Returned"

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET return_status=%s, status=%s
        WHERE id=%s
    """, (verdict, status, order_id))
    db.commit()
    cur.close()
    db.close()

    return render_template(
        "return_result.html",
        order_id=order_id,
        matched=matched,
        mismatched=mismatched,
        accuracy=accuracy,
        confidence=avg_conf,
        verdict=verdict,
        message=message
    )



@app.route("/return/accept/<int:order_id>")
def accept_return(order_id):
    if session.get("role") != "return":
        return redirect("/return/login")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET status='Return Accepted'
        WHERE id=%s
    """, (order_id,))
    db.commit()

    flash("Return accepted.")
    return redirect("/return/dashboard")

@app.route("/return/reject/<int:order_id>")
def reject_return(order_id):
    if session.get("role") != "return":
        return redirect("/return/login")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        UPDATE orders
        SET status='Return Rejected',
            return_reject_reason=%s
        WHERE id=%s
    """, ("Mismatch in returned items", order_id))
    db.commit()

    flash("Return rejected.")
    return redirect("/return/dashboard")



# ======================================================
# LOGOUT
# ======================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ======================================================
# RUN
# ======================================================
if __name__ == "__main__":
    app.run(debug=True)
