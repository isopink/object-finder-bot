from glob import glob

from setuptools import setup

PACKAGE = "objmem_ros"

setup(
    name=PACKAGE,
    version="0.1.0",
    packages=[PACKAGE],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + PACKAGE]),
        ("share/" + PACKAGE, ["package.xml"]),
        ("share/" + PACKAGE + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="object-finder-bot team",
    maintainer_email="noreply@example.com",
    description="ROS 2 nodes for the object-finder robot",
    license="MIT",
    entry_points={
        "console_scripts": [
            "objmem = objmem_ros.nodes:main_all",
            "observer = objmem_ros.nodes:main_observer",
            "finder = objmem_ros.nodes:main_finder",
            "mapview = objmem_ros.nodes:main_mapview",
            "ask = objmem_ros.ask:main",
            "fake_nav2 = objmem_ros.fake_nav2:main",
        ],
    },
)
