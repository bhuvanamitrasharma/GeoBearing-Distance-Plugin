def classFactory(iface):
    from .distance_bearing_plugin import GeoBearingDistancePlugin
    return GeoBearingDistancePlugin(iface)
