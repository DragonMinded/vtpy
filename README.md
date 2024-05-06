# pyvt

A simple library for abstracting talking to a VT-100 terminal over serial or stdin/stdout redirects. You can include this in your project by adding the line `vtpy @ git+https://github.com/DragonMinded/vtpy.git` to your requirements.txt file, or adding it as a requirement to your alternative dependency management system of choice. If you are non-technical and looking to run this, you won't find anything here. This is just a library that can be used in other python programs and offers nothing that can be run by itself.

## Development

This package is black, lint and type-hint clean! Please keep it this way. To install the required dependencies for this project when developing, run the following two lines. The first installs dependencies for runtime, and the second installs tool dependencies.

```
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-dev.txt
```

To auto-format files after changes, run the following in the root of the project:

```
black .
```

To check for lint errors or type violations, run the following in the root of the project:

```
mypy .
flake8 .
```
