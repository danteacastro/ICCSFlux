# NISystem Launcher Package
# Note: Imports are lazy to avoid circular import warnings when running as __main__
__all__ = ['ServiceManager', 'cleanup_orphaned_processes']

def __getattr__(name):
    if name == 'ServiceManager':
        from .service_manager import ServiceManager
        return ServiceManager
    elif name == 'cleanup_orphaned_processes':
        from .service_manager import cleanup_orphaned_processes
        return cleanup_orphaned_processes
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
