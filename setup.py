from setuptools import setup
from setuptools.command.build_ext import build_ext as _build_ext

# From http://stackoverflow.com/a/21621689 because numpy is total garbage
class build_ext(_build_ext):
    def finalize_options(self):
        _build_ext.finalize_options(self)
        # Prevent numpy from thinking it is still in its setup process:
        __builtins__.__NUMPY_SETUP__ = False
        import numpy
        self.include_dirs.append(numpy.get_include())

setup(
        name='reduction',
        version='0.1.0',
        author='Edward Paget',
        author_email='ed@zooniverse.org',
        packages=['reduction', 'reduction.adapters', 'reduction.algos'] ,
        scripts=['bin/zoo-reduce'],
        url='http://github.com/zooniverse/reduction',
        license='LICENSE',
        cmdclass={'build_ext':build_ext},
        setup_requires=['numpy==1.8.1'],
        description='Reduces crowdsourced data from Zooniverse projects',
        long_description=open('README.md').read(),
        install_requires=[
            "networkx==1.8.1",
            "pymongo==2.7",
            "scipy==0.13.3",
            "numpy==1.8.1",
            "pymysql==0.6.2"
            ]
        )
