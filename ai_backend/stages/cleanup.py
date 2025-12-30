import cv2
import numpy as np
import logging
from .base import BaseStage

logger = logging.getLogger("ai_backend.stages.cleanup")


class CleanupStage(BaseStage):
    def __init__(self):
        super().__init__("cleanup")
        self.valid_input_slugs = ["outline", "original", "i2i"]

    def process(self, input_path, params, job_info):
        """
        Cleans up an image (histogram thresholding, dilation, donut logic)
        to prepare it for centerline tracing or other uses.
        """
        logger.debug(f"Starting cleanup process with input: {input_path}")
        logger.debug(f"Params: {params}")

        image = cv2.imread(input_path, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError(f"Could not read image from {input_path}")

        logger.debug(f"Original image shape: {image.shape}, dtype: {image.dtype}")
        logger.debug(
            f"Original image value range: min={image.min()}, max={image.max()}"
        )

        # Handle alpha channel or grayscale
        if len(image.shape) == 2:
            logger.debug("Converting grayscale to BGR")
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            logger.debug("Compositing alpha channel on white background")
            # Composite on white
            alpha = image[:, :, 3] / 255.0
            image_rgb = image[:, :, :3]
            white_bg = np.ones_like(image_rgb) * 255
            image = (
                image_rgb * alpha[:, :, np.newaxis]
                + white_bg * (1 - alpha[:, :, np.newaxis])
            ).astype(np.uint8)
            logger.debug(
                f"After alpha composite - min={image.min()}, max={image.max()}"
            )

        if np.all(image < 30):
            raise ValueError("Image is all black")

        # Histogram and Thresholding
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        v_channel = hsv[:, :, 2]

        logger.debug(
            f"V channel stats - min={v_channel.min()}, max={v_channel.max()}, mean={v_channel.mean():.2f}"
        )
        logger.debug(f"V channel unique values count: {len(np.unique(v_channel))}")

        # Build histogram of V (0..255)
        hist = (
            cv2.calcHist([v_channel], [0], None, [256], [0, 256])
            .flatten()
            .astype(np.float32)
        )

        logger.debug(f"Histogram non-zero bins: {np.count_nonzero(hist)}")
        logger.debug(f"Histogram max count: {hist.max()}")

        # Smooth the histogram
        kernel_size = params.get("hist_smooth_kernel", 5)
        hist_kernel = np.ones(kernel_size, dtype=np.float32) / float(kernel_size)
        smooth = np.convolve(hist, hist_kernel, mode="same")

        logger.debug(f"Smoothed histogram max: {smooth.max()}")

        # Find local maxima (peaks)
        peaks = [
            (i, smooth[i])
            for i in range(1, 255)
            if smooth[i] > smooth[i - 1] and smooth[i] >= smooth[i + 1]
        ]

        logger.debug(f"Found {len(peaks)} total peaks")
        if peaks:
            logger.debug(f"Peak bins: {[p[0] for p in peaks[:10]]}")  # Show first 10

        # Filter out tiny peaks (noise)
        peak_threshold_ratio = params.get("peak_threshold_ratio", 0.02)
        meaningful_peaks = []
        if peaks:
            max_count = max(p[1] for p in peaks)
            meaningful_peaks = [
                (b, c) for (b, c) in peaks if c >= peak_threshold_ratio * max_count
            ]
            logger.debug(f"Filtered to {len(meaningful_peaks)} meaningful peaks")
            if meaningful_peaks:
                logger.debug(
                    f"Meaningful peak bins: {[p[0] for p in meaningful_peaks]}"
                )

        # Choose threshold
        threshold_val = params.get("threshold_val")
        threshold_offset = params.get("threshold_offset", 16)

        if threshold_val is None:
            if meaningful_peaks:
                # Find the darkest meaningful peak that's actually dark (< 200)
                dark_peaks = [p for p in meaningful_peaks if p[0] < 200]

                if dark_peaks:
                    darkest_peak_bin = min(dark_peaks, key=lambda x: x[0])[0]
                    threshold_val = min(int(darkest_peak_bin) + threshold_offset, 255)
                    logger.debug(
                        f"Threshold from darkest peak: {darkest_peak_bin} + {threshold_offset} = {threshold_val}"
                    )
                else:
                    # All peaks are bright - image is mostly white
                    # Look for the darkest pixels instead
                    logger.debug(
                        "All peaks are bright (>200), using percentile approach"
                    )
                    low_percentile = np.percentile(v_channel, 5)
                    threshold_val = min(int(low_percentile) + threshold_offset, 240)
                    logger.debug(
                        f"Threshold from 5th percentile: {low_percentile:.2f} + {threshold_offset} = {threshold_val}"
                    )
            else:
                low_percentile = np.percentile(v_channel, 5)
                threshold_val = min(int(low_percentile) + threshold_offset, 240)
                logger.debug(
                    f"Threshold from 5th percentile: {low_percentile:.2f} + {threshold_offset} = {threshold_val}"
                )

        # Cap threshold to avoid the 255 issue
        threshold_val = min(threshold_val, 240)
        logger.info(f"Using threshold {threshold_val}")

        # Apply threshold
        _, binary = cv2.threshold(v_channel, threshold_val, 255, cv2.THRESH_BINARY)

        white_pixels = np.sum(binary == 255)
        black_pixels = np.sum(binary == 0)
        total_pixels = binary.size
        logger.debug(
            f"After threshold - White: {white_pixels} ({100*white_pixels/total_pixels:.1f}%), Black: {black_pixels} ({100*black_pixels/total_pixels:.1f}%)"
        )

        # Cleanup morphological operations
        dilation_iterations = params.get("dilation_iterations", 10)
        morph_kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(binary, morph_kernel, iterations=dilation_iterations)

        white_pixels_dilated = np.sum(dilated == 255)
        black_pixels_dilated = np.sum(dilated == 0)
        logger.debug(
            f"After dilation - White: {white_pixels_dilated} ({100*white_pixels_dilated/total_pixels:.1f}%), Black: {black_pixels_dilated} ({100*black_pixels_dilated/total_pixels:.1f}%)"
        )

        final = binary.copy()

        # Donut logic: remove interior of thick objects
        # User defined this to help centerline find the "middle" of the boundary
        final[np.where(dilated == 0)] = 255

        white_pixels_final = np.sum(final == 255)
        black_pixels_final = np.sum(final == 0)
        logger.debug(
            f"After donut logic - White: {white_pixels_final} ({100*white_pixels_final/total_pixels:.1f}%), Black: {black_pixels_final} ({100*black_pixels_final/total_pixels:.1f}%)"
        )

        if white_pixels_final == total_pixels:
            logger.warning("WARNING: Final image is completely white!")
        elif black_pixels_final == total_pixels:
            logger.warning("WARNING: Final image is completely black!")

        # Resize if requested
        target_size = params.get("target_size", 512)
        if target_size:
            logger.debug(f"Resizing to {target_size}x{target_size}")
            final = cv2.resize(
                final, (target_size, target_size), interpolation=cv2.INTER_AREA
            )
            logger.debug(f"After resize - min={final.min()}, max={final.max()}")

        output_path = self.save_hashed_file(
            cv2.imencode(".png", final)[1].tobytes(), ".png"
        )
        logger.debug(f"Saved output to: {output_path}")
        return {"cleanup": output_path}
