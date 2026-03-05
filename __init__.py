def classFactory(iface):
    from .distance_bearing_plugin import DistanceBearingPlugin
    return DistanceBearingPlugin(iface)
