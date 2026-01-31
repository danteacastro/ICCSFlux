"""
Entry point for running cRIO Node V2 as a module.

Usage:
    python -m crio_node_v2 --config ./crio_config.json
"""

from .crio_node import main

if __name__ == '__main__':
    main()
