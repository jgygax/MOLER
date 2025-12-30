FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04
WORKDIR /app

# Install system dependencies
# Note: graphics libraries and build tools are needed for autotrace and opencv
RUN apt-get update && \
    apt-get install -y \
    wget \
    git \
    build-essential \
    autoconf \
    automake \
    libtool \
    intltool \
    pkg-config \
    libtiff5 \
    libgl1 \
    libglib2.0-0 \
    libglib2.0-dev \
    python3-pip \
    imagemagick \
    libmagickcore-6.q16-6 \
    libmagickcore-6.q16-dev \
    libmagick++-6.q16-dev \
    libpng-dev \
    libpstoedit0c2a \
    libpstoedit-dev \
    libexif12 \
    libexif-dev \
    autopoint \
    && rm -rf /var/lib/apt/lists/*

# Build and install autotrace from source (Required for Centerline stage)
RUN cd /tmp && \
    git clone https://github.com/autotrace/autotrace.git && \
    cd autotrace && \
    ./autogen.sh && \
    ./configure && \
    make && \
    make install && \
    ldconfig && \
    cd / && \
    rm -rf /tmp/autotrace && \
    autotrace --version

# Copy and install Python requirements
COPY requirements.txt .
# Using --extra-index-url to ensure we get CUDA-enabled torch if using standard pip repository
RUN pip install --no-cache-dir -r requirements.txt

WORKDIR /app

COPY . .

# Create directory structure for cache if needed
RUN mkdir -p /app/models

EXPOSE 5002

CMD ["gunicorn", "--worker-class", "gthread", "--threads", "4", "--bind", "0.0.0.0:5002", "app:app"]
