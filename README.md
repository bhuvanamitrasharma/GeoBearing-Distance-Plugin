# Distance Bearing Tool

The **Distance Bearing Tool** is a precision digitizing tool designed for creating features via ellipsoidal distance and bearing. It serves as a perfect complement to the native **Advanced Digitizing Panel**, allowing for the creation of lines and polygons based on exact geographic inputs.

## ✈️ Why Use This Tool?
Standard digitizing tools often rely on Grid-based calculations limited by the project's CRS. This tool utilizes **ellipsoidal accuracy**, ensuring that calculations remain precise regardless of your map canvas CRS. This makes it an essential utility for **aviation**, navigation, and survey-grade plotting where True North and geodesic distances are required.

## 🌟 Key Features
* **Ellipsoidal Accuracy:** Calculations remain precise regardless of your map canvas CRS.
* **Seamless Integration:** Works with standard QGIS snapping and digitizing workflows.
* **Precision Plotting:** Ideal for aviation-standard plotting and geometric construction.
* **Live UI Feedback:** Displays real-time geodesic bearing and distance during digitizing.
* **Constraint Locking:** Ability to lock specific bearing or distance values for high-accuracy placement.

## 🛠 How It Works
1. **Enable Editing:** Toggle editing on the desired vector layer.
2. **Select Tool:** Click the Distance Bearing Tool icon in the digitizing toolbar.
3. **Set Origin:** Click on the map to place your first vertex.
4. **Input Data:** - Enter values manually in the **Bearing CAD Controls** dock and click **Add Point**.
   - Use the **Lock** checkboxes to constrain the mouse movement to a specific bearing or distance.
5. **Finalize:** Right-click or select **Finish** to commit the feature geometry.

## 📋 Technical Details
* **Calculation Basis:** WGS84 Ellipsoid (Geodesic).
* **Bearing Reference:** 0° to 360° (True North).
* **Compatibility:** QGIS 3.0+.

---
*Developed by Bhuvanamitra S*
