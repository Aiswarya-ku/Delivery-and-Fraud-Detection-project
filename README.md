**E-commerce Delivery & Fraud Detection System**
This is a full-stack Flask application designed to prevent e-commerce fraud by verifying products during the packing, delivery, and return stages using Computer Vision.

🚀 Key Features
AI-Powered Object Detection: Utilizes the YOLOv8 model to identify and track products in video streams.

Automated Verification: Compares "Packing Videos" from sellers with "Delivery Videos" from partners to ensure the customer receives exactly what was sent.

Return Fraud Prevention: Analyzes return videos to verify if the product being sent back matches the original item delivered.

Multi-User Dashboard: Specialized interfaces for Admins, Sellers, Customers, and Delivery Partners.

Real-time Streaming: Uses OpenCV to generate live video feeds with detection overlays (bounding boxes) for transparency.

🛠️ Tech Stack
Backend: Python (Flask)

Computer Vision: OpenCV, Ultralytics (YOLOv8), Scikit-image (SSIM for similarity)

Database: MySQL

Frontend: HTML5, CSS3 (Jinja2 templates)

🧠 How the Logic Works
Detection: YOLOv8 detects objects in each video frame, specifically ignoring "person" classes to focus solely on products.

Unique Object Tracking: The system uses SSIM and IoU (Intersection over Union) to ensure it doesn't count the same object twice across different frames.

Comparison: It calculates the Euclidean distance between object features to determine a "Match" or "Mismatch" score, providing an accuracy percentage for every delivery.

