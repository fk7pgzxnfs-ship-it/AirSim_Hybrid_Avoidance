from setuptools import setup, find_packages

setup(
    name="airsim_hybrid_avoidance",
    version="1.0.0",
    description="AirSim Hybrid Avoidance - 无人机混合避障导航系统",
    author="Your Name",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "numpy",
        "pyyaml",
        "matplotlib",
        "torch",
        "gymnasium",
        "pandas",
        "tqdm",
    ],
)