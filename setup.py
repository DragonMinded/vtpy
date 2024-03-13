from distutils.core import setup

setup(
    name="VTPy",
    version="1.0.8",
    description="Python abstraction layer for VT-100 terminals.",
    author="Jennifer Taylor",
    author_email="jen@superjentendo.com",
    url="https://github.com/DragonMinded/vtpy",
    packages=["vtpy"],
    requires=["pySerial"],
    include_package_data=True,
)
