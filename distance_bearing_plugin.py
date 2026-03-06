import math
import os
try:
    import sip
except ImportError:
    try:
        from PyQt5 import sip
    except ImportError:
        sip = None

from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand, QgsSnapIndicator, QgsDockWidget, QgsAdvancedDigitizingDockWidget
from qgis.core import (
    QgsWkbTypes, QgsProject, QgsUnitTypes,
    QgsMessageLog, Qgis, QgsPointXY, QgsGeometry, QgsFeature,
    QgsMapLayer, QgsTolerance, QgsCoordinateTransform, QgsPointLocator,
    QgsCoordinateReferenceSystem, QgsDistanceArea
)
from qgis.utils import iface
from qgis.PyQt.QtCore import Qt, QTimer, pyqtSignal, QSize
from qgis.PyQt.QtWidgets import (
    QInputDialog, QDialog, QFormLayout, QDoubleSpinBox, 
    QDialogButtonBox, QVBoxLayout, QDockWidget, QWidget,
    QCheckBox, QPushButton, QLabel, QHBoxLayout, QAction
)
from qgis.PyQt.QtGui import QColor, QIcon

def is_deleted(obj):
    """Safe check for deleted C++ objects"""
    if obj is None: return True
    if sip is not None:
        try: return sip.isdeleted(obj)
        except: pass
    return False

class BearingDockWidget(QgsDockWidget):
    """Docked panel for live bearing/distance and constraint locking"""
    closingWidget = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("GeoBearing-Distance", parent)
        self.setObjectName("GeoBearing-DistanceDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        # Main Layout
        self.main_widget = QWidget()
        self.layout = QVBoxLayout(self.main_widget)

        # Header
        header = QLabel("<b>GeoBearing-Distance Controls</b>")
        self.layout.addWidget(header)

        # --- Bearing Input ---
        bearing_row = QHBoxLayout()
        bearing_row.addWidget(QLabel("Bearing:"))
        self.bearing_box = QDoubleSpinBox()
        self.bearing_box.setRange(0, 360)
        self.bearing_box.setDecimals(4)
        self.bearing_box.setSuffix("°")
        bearing_row.addWidget(self.bearing_box)
        
        self.bearing_lock = QCheckBox("Lock")
        bearing_row.addWidget(self.bearing_lock)
        self.layout.addLayout(bearing_row)

        # --- Distance Input ---
        dist_row = QHBoxLayout()
        dist_row.addWidget(QLabel("Distance:"))
        self.distance_box = QDoubleSpinBox()
        self.distance_box.setRange(0, 999999999)
        self.distance_box.setDecimals(4)
        dist_row.addWidget(self.distance_box)
        
        self.distance_lock = QCheckBox("Lock")
        dist_row.addWidget(self.distance_lock)
        self.layout.addLayout(dist_row)

        # (True North toggle removed - now default)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Point")
        self.btn_finish = QPushButton("Finish")
        self.btn_reset = QPushButton("Reset")
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_finish)
        btn_row.addWidget(self.btn_reset)
        self.layout.addLayout(btn_row)

        self.btn_close = QPushButton("Close Tool")
        self.layout.addWidget(self.btn_close)

        self.setWidget(self.main_widget)

    def closeEvent(self, event):
        self.closingWidget.emit()
        super().closeEvent(event)

class BearingCADTool(QgsMapToolEmitPoint):
    """Map Tool for high-precision digitizing with Bearing/Distance constraints"""
    def __init__(self, canvas, dock):
        super().__init__(canvas)
        self.canvas = canvas
        self.dock = dock
        self.vertices = []

        self.snap_indicator = QgsSnapIndicator(canvas)

        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self.rubber_band.setColor(Qt.red)
        self.rubber_band.setWidth(2)
        color = QColor(Qt.red)
        color.setAlpha(100)
        self.rubber_band.setFillColor(color)

        self.setCursor(Qt.CrossCursor)

        self.live_bearing = 0.0
        self.live_dist = 0.0

        self.live_bearing = 0.0
        self.live_dist = 0.0

        # Geodesic Math Engine
        self.da = QgsDistanceArea()
        self._last_crs = None
        self._last_ellipsoid = None
        self.setup_da()
        
        QgsMessageLog.logMessage("GeoBearing-Distance (Geodesic v2) Initialized", "GeoBearing-Distance", Qgis.Info)

        # Sync with Native CAD panel
        self.cad_dock = iface.cadDockWidget()
        if self.cad_dock:
            try:
                # Mirror native CAD locks
                self.cad_dock.orderConfigChanged.connect(self.sync_from_native_cad)
            except: pass

    def setup_da(self):
        """Configures the geodesic engine (Forced to WGS84 for maximum stability)"""
        self.da.setSourceCrs(QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance().transformContext())
        self.da.setEllipsoid("WGS84")

    def project_geodesic(self, p1, dist, bearing_deg):
        """Robustly projects a point on the ellipsoid using WGS84 intermediate step"""
        self.setup_da()
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        
        # 1. Transform to WGS84
        x_to_wgs = QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
        p1_geo = x_to_wgs.transform(p1)
        
        # 2. Project on Ellipsoid (WGS84 context is bulletproof)
        bearing_rad = math.radians(bearing_deg)
        p2_geo = self.da.computeSpheroidProject(p1_geo, dist, bearing_rad)
        
        # 3. Transform back to Map CRS
        x_to_map = QgsCoordinateTransform(wgs84, canvas_crs, QgsProject.instance())
        return x_to_map.transform(p2_geo)

    def measure_geodesic(self, p1, p2):
        """Measures distance and bearing between two points on the ellipsoid"""
        self.setup_da()
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        
        x_to_wgs = QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
        p1_geo = x_to_wgs.transform(p1)
        p2_geo = x_to_wgs.transform(p2)
        
        # Guard against identical points (prevents NaN bearing)
        if p1_geo.distance(p2_geo) < 1e-9:
            return 0.0, 0.0
            
        dist = self.da.measureLine(p1_geo, p2_geo)
        bearing_rad = self.da.bearing(p1_geo, p2_geo)
        bearing_deg = (math.degrees(bearing_rad) + 360) % 360
        
        return dist, bearing_deg

    # ---------------- TOOL LIFECYCLE ----------------
    def activate(self):
        if is_deleted(self.dock): return
        super().activate()
        self.dock.show()
        try:
            self.dock.btn_add.clicked.connect(self.add_constrained_vertex)
            self.dock.btn_finish.clicked.connect(self.commit_geometry)
            self.dock.btn_reset.clicked.connect(self.reset_tool)
            self.dock.btn_close.clicked.connect(self.close_tool)
            
            # Connect Sync
            self.dock.distance_box.valueChanged.connect(self.sync_to_native_cad)
            self.dock.bearing_box.valueChanged.connect(self.sync_to_native_cad)
            self.dock.distance_lock.stateChanged.connect(self.sync_to_native_cad)
            self.dock.bearing_lock.stateChanged.connect(self.sync_to_native_cad)
        except: pass
        
        QgsMessageLog.logMessage("BearingCAD activated", "BearingCAD", Qgis.Info)

    def deactivate(self):
        if not is_deleted(self.dock):
            try:
                self.dock.btn_add.clicked.disconnect(self.add_constrained_vertex)
                self.dock.btn_finish.clicked.disconnect(self.commit_geometry)
                self.dock.btn_reset.clicked.disconnect(self.reset_tool)
                self.dock.btn_close.clicked.disconnect(self.close_tool)
                
                # Disconnect Sync
                self.dock.distance_box.valueChanged.disconnect(self.sync_to_native_cad)
                self.dock.bearing_box.valueChanged.disconnect(self.sync_to_native_cad)
                self.dock.distance_lock.stateChanged.disconnect(self.sync_to_native_cad)
                self.dock.bearing_lock.stateChanged.disconnect(self.sync_to_native_cad)
            except: pass
        
        self.snap_indicator.setMatch(QgsPointLocator.Match())
        super().deactivate()

    def close_tool(self):
        self.canvas.unsetMapTool(self)
        if not is_deleted(self.dock):
            self.dock.hide()

    # ---------------- CLICK EVENTS ----------------
    def canvasReleaseEvent(self, e):
        if is_deleted(self.dock): return
        if e.button() == Qt.RightButton:
            e.accept()
            self.commit_geometry()
            return

        e.accept()
        raw_pt, is_snapped = self.get_snapped_point(e)
        
        # If locked AND not snapped, use constrained point
        pt = raw_pt
        if self.vertices and not is_snapped:
            if self.dock.bearing_lock.isChecked() or self.dock.distance_lock.isChecked():
                pt = self.calc_constrained_point(self.vertices[-1], raw_pt)

        self.add_vertex(pt)

    def add_constrained_vertex(self):
        """Triggered from 'Add Point' button using UI values"""
        if not self.vertices:
            # First point must be a click or we use 0,0 (not useful)
            iface.messageBar().pushMessage("GeoBearing-Distance", "Place the first point on canvas first.", Qgis.Warning)
            return
            
        # Calculate next point from last vertex + UI Bearing/Dist
        p1 = self.vertices[-1]
        bearing_deg = self.dock.bearing_box.value()
        dist = self.dock.distance_box.value()
        
        # Always use Geodesic math (bulletproof transformation flow)
        new_pt = self.project_geodesic(p1, dist, bearing_deg)
        self.add_vertex(new_pt)

    # ---------------- CORE LOGIC ----------------
    def get_snapped_point(self, e):
        """Uses native QGIS snapping config + self-snapping for current vertices"""
        config = self.canvas.snappingUtils().config()
        map_pt = self.toMapCoordinates(e.pos())
        
        # 1. Try Native Snapping
        if config.enabled():
            match = self.canvas.snappingUtils().snapToMap(e.pos())
            if match.isValid():
                self.snap_indicator.setMatch(match)
                return match.point(), True

        # 2. Self-Snapping (to our own vertices)
        if self.vertices:
            # Calculate pixel tolerance (standard QGIS is usually 10-12 pixels)
            tolerance_map = 10 * self.canvas.mapSettings().mapUnitsPerPixel()
            
            for v in self.vertices:
                if v.distance(map_pt) < tolerance_map:
                    # Create a dummy match for the indicator
                    fake_match = QgsPointLocator.Match(QgsPointLocator.Vertex, None, -1, 0.0, v)
                    self.snap_indicator.setMatch(fake_match)
                    return v, True

        self.snap_indicator.setMatch(QgsPointLocator.Match())
        return map_pt, False

    def canvasMoveEvent(self, e):
        if is_deleted(self.dock): return
        super().canvasMoveEvent(e)
        
        raw_pt, is_snapped = self.get_snapped_point(e)
        curr_pt = raw_pt

        if self.vertices:
            last_pt = self.vertices[-1]
            
            # Apply constraints to preview if locked
            if not is_snapped and (self.dock.bearing_lock.isChecked() or self.dock.distance_lock.isChecked()):
                curr_pt = self.calc_constrained_point(last_pt, raw_pt)
                
            # Calculate Geodesic Bearing & Distance
            self.live_dist, self.live_bearing = self.measure_geodesic(last_pt, curr_pt)
            
            # Update UI (only if NOT locked)
            if not self.dock.bearing_lock.isChecked():
                self.dock.bearing_box.setValue(self.live_bearing)
            if not self.dock.distance_lock.isChecked():
                self.dock.distance_box.setValue(self.live_dist)
            
            self.update_preview(curr_pt)

    def calc_constrained_point(self, p1, p_mouse):
        """Projects mouse point onto constrained angle or distance"""
        dist = self.dock.distance_box.value()
        angle_deg = self.dock.bearing_box.value()
        
        self.setup_da()
        
        # If both locked, it's a fixed coordinate
        if self.dock.bearing_lock.isChecked() and self.dock.distance_lock.isChecked():
            return self.project_geodesic(p1, dist, angle_deg)
        
        # If ONLY distance locked, keep dist, use current mouse bearing
        if self.dock.distance_lock.isChecked():
            _, mouse_brng = self.measure_geodesic(p1, p_mouse)
            return self.project_geodesic(p1, dist, mouse_brng)
            
        # If ONLY bearing locked, mouse distance determines how far along the ray we go
        if self.dock.bearing_lock.isChecked():
            m_dist, _ = self.measure_geodesic(p1, p_mouse)
            return self.project_geodesic(p1, m_dist, angle_deg)
            
        return p_mouse


    # ---------------- UI HELPERS ----------------
    def update_preview(self, curr_pt=None):
        self.rubber_band.reset()
        for v in self.vertices:
            self.rubber_band.addPoint(v)
        if curr_pt:
            self.rubber_band.addPoint(curr_pt)

    def sync_to_native_cad(self):
        """Pushes our tool locks into the native QGIS CAD panel (if open)"""
        if not self.cad_dock: return
        try:
            # We use QTimer to avoid recursion if sync is bi-directional
            QTimer.singleShot(10, self._perform_sync_to_native)
        except: pass

    def _perform_sync_to_native(self):
        if not self.cad_dock.isEnabled(): return
        # QGIS CAD panel uses 'd' for distance and 'a' for angle (polar)
        try: 
            # Note: native CAD angle is Cartesian (0 East), we are North=0
            # We won't force values to avoid confusion, just sync locks
            self.cad_dock.setConstraintValue(QgsAdvancedDigitizingDockWidget.Distance, self.dock.distance_box.value())
            self.cad_dock.setConstraintLocked(QgsAdvancedDigitizingDockWidget.Distance, self.dock.distance_lock.isChecked())
            
            # Angle is complex due to diff North definitions, so we mostly sync 'locked' state 
            # to prevent user from fighting two panels.
            self.cad_dock.setConstraintLocked(QgsAdvancedDigitizingDockWidget.Angle, self.dock.bearing_lock.isChecked())
        except: pass

    def sync_from_native_cad(self):
        """Pulls locks from native QGIS CAD panel into our tool"""
        if is_deleted(self.dock): return
        try:
            self.dock.distance_lock.setChecked(self.cad_dock.constraintLocked(QgsAdvancedDigitizingDockWidget.Distance))
            self.dock.bearing_lock.setChecked(self.cad_dock.constraintLocked(QgsAdvancedDigitizingDockWidget.Angle))
        except: pass

    # ---------------- ADD VERTEX ----------------
    def add_vertex(self, pt):
        if is_deleted(self.dock): return

        self.vertices.append(pt)
        self.update_preview()

        # Reset locks for next segment
        self.dock.bearing_lock.setChecked(False)
        self.dock.distance_lock.setChecked(False)

        layer = iface.activeLayer()
        if not layer:
            return

        if not layer.isEditable():
            layer.startEditing()

        if layer.geometryType() == QgsWkbTypes.PointGeometry:
            # Transform point to Layer CRS
            layer_pt = pt
            canvas_crs = self.canvas.mapSettings().destinationCrs()
            layer_crs = layer.crs()
            if canvas_crs != layer_crs:
                xform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
                layer_pt = xform.transform(pt)

            geom = QgsGeometry.fromPointXY(layer_pt)
            
            # Use native vectorLayerTools to trigger attribute dialog and handle topology
            iface.vectorLayerTools().addFeature(layer, {}, geom)
            
            layer.triggerRepaint()
            self.reset_tool()

    # ---------------- COMMIT ----------------
    def commit_geometry(self):
        layer = iface.activeLayer()
        if not layer or len(self.vertices) < 2:
            self.reset_tool()
            return

        if not layer.isEditable():
            layer.startEditing()

        # Transform ALL vertices to Layer CRS
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()
        layer_pts = []
        if canvas_crs != layer_crs:
            xform = QgsCoordinateTransform(canvas_crs, layer_crs, QgsProject.instance())
            layer_pts = [xform.transform(v) for v in self.vertices]
        else:
            layer_pts = self.vertices[:]

        feat_geom = None

        if layer.geometryType() == QgsWkbTypes.LineGeometry:
            feat_geom = QgsGeometry.fromPolylineXY(layer_pts)

        elif layer.geometryType() == QgsWkbTypes.PolygonGeometry:
            if len(layer_pts) < 3:
                iface.messageBar().pushWarning("GeoBearing-Distance", "Polygon needs at least 3 vertices.")
                self.reset_tool()
                return
                
            pts = layer_pts[:]
            if pts[0] != pts[-1]:
                pts.append(pts[0])

            geom = QgsGeometry.fromPolygonXY([pts])
            if QgsWkbTypes.isMultiType(layer.wkbType()):
                geom = QgsGeometry.fromMultiPolygonXY([[pts]])
            
            geom.makeValid()
            feat_geom = geom

        # Use native vectorLayerTools to trigger attribute dialog and handle topology
        if feat_geom:
            success = iface.vectorLayerTools().addFeature(layer, {}, feat_geom)
            if success:
                iface.mainWindow().statusBar().showMessage("Feature Added Successfully", 3000)

        layer.triggerRepaint()
        self.reset_tool()

    # ---------------- RESET ----------------
    def reset_tool(self):
        self.vertices.clear()
        self.rubber_band.reset()
        iface.mainWindow().statusBar().clearMessage()

class GeoBearingDistancePlugin:
    """Main Plugin class for GeoBearing-Distance"""
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.dock = None
        self.tool = None
        self.is_swapping = False
        self.connected_layers = set()
        self.action = None

    def initGui(self):
        # Create Dock Widget
        self.dock = BearingDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()

        # Create Map Tool
        self.tool = BearingCADTool(self.canvas, self.dock)

        # Create Toolbar Action
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        
        self.action = QAction(icon, "Switch to GeoBearing-Distance", self.iface.mainWindow())
        self.action.setToolTip("Switch the current feature creation to high-precision GeoBearing-Distance")
        self.action.setCheckable(True)
        self.action.setEnabled(False)
        self.action.triggered.connect(self.toggle_bearing_mode)
        
        # Add to Digitizing Toolbar
        self.iface.digitizeToolBar().addAction(self.action)
        
        # Connect Signals for dynamic updates
        self.canvas.mapToolSet.connect(self.on_map_tool_set)
        self.iface.currentLayerChanged.connect(self.refresh_action_state)
        
        # Connect dock closing
        self.dock.closingWidget.connect(lambda: self.canvas.unsetMapTool(self.tool))

        self.refresh_action_state()

    def unload(self):
        # 1. Surgical Signal Cleanup
        try: self.iface.currentLayerChanged.disconnect(self.refresh_action_state)
        except: pass
        try: self.canvas.mapToolSet.disconnect(self.on_map_tool_set)
        except: pass
        
        for layer in list(self.connected_layers):
            try:
                layer.editingStarted.disconnect(self.refresh_action_state)
                layer.editingStopped.disconnect(self.refresh_action_state)
            except: pass
        self.connected_layers.clear()

        # 2. UI Cleanup
        if self.action:
            self.iface.digitizeToolBar().removeAction(self.action)
        
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        # 3. Tool Cleanup
        if self.canvas.mapTool() == self.tool:
            self.canvas.unsetMapTool(self.tool)
        self.tool = None

    def refresh_action_state(self):
        """Forces a refresh of the action enabled/checked state with a slight delay"""
        if self.is_swapping: return
        QTimer.singleShot(100, lambda: self.on_map_tool_set(self.canvas.mapTool()))

    def on_map_tool_set(self, new_tool):
        if self.is_swapping: return
        layer = self.iface.activeLayer()
        tool_name = type(new_tool).__name__ if new_tool else "None"
        
        # Track layer signals
        if layer and layer not in self.connected_layers:
            try:
                layer.editingStarted.connect(self.refresh_action_state)
                layer.editingStopped.connect(self.refresh_action_state)
                self.connected_layers.add(layer)
            except: pass

        if not self.action: return

        if tool_name == "BearingCADTool":
            # Guard: If editing is turned off, force deactivate our tool
            if not layer or not layer.isEditable():
                if self.tool is not None and self.canvas.mapTool() == self.tool:
                    self.canvas.unsetMapTool(self.tool)
                if self.dock is not None: 
                    self.dock.hide()
                return

            self.action.setEnabled(True)
            self.action.setChecked(True)
            return

        # Native swaps
        native_keywords = ["Digitize", "AddFeature", "AddPart", "Capture", "Shape", "Polygon", "Line", "Point"]
        is_native_add = any(kw.lower() in tool_name.lower() for kw in native_keywords)
        
        if is_native_add:
            if layer and layer.isEditable() and layer.geometryType() in [QgsWkbTypes.LineGeometry, QgsWkbTypes.PolygonGeometry, QgsWkbTypes.PointGeometry]:
                self.action.setEnabled(True)
                self.action.setChecked(False)
                return

        self.action.setEnabled(False)
        self.action.setChecked(False)

    def toggle_bearing_mode(self, checked):
        self.is_swapping = True
        if checked:
            self.canvas.setMapTool(self.tool)
            if self.dock is not None:
                self.dock.show()
        else:
            if self.tool is not None and self.canvas.mapTool() == self.tool:
                self.canvas.unsetMapTool(self.tool)
            if self.dock is not None: 
                self.dock.hide()
        self.is_swapping = False
