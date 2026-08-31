using System;

namespace DSPDreamer.CaptureProbe
{
    public sealed class CursorGlyph
    {
        public CursorGlyph(int width, int height, byte[] rgbaTopDown)
        {
            if (width <= 0) throw new ArgumentOutOfRangeException("width");
            if (height <= 0) throw new ArgumentOutOfRangeException("height");
            if (rgbaTopDown == null) throw new ArgumentNullException("rgbaTopDown");
            if (rgbaTopDown.Length != checked(width * height * 4)) throw new ArgumentException("Cursor RGBA length does not match its dimensions.", "rgbaTopDown");
            Width = width;
            Height = height;
            RgbaTopDown = rgbaTopDown;
        }

        public int Width { get; private set; }
        public int Height { get; private set; }
        public byte[] RgbaTopDown { get; private set; }
    }

    public static class CursorCompositor
    {
        public static int Composite(byte[] frame, int frameWidth, int frameHeight, CursorGlyph glyph, int left, int top, int drawWidth, int drawHeight)
        {
            if (frame == null) throw new ArgumentNullException("frame");
            if (glyph == null) throw new ArgumentNullException("glyph");
            if (frameWidth <= 0 || frameHeight <= 0 || frame.Length != checked(frameWidth * frameHeight * 4))
            {
                throw new ArgumentException("Frame RGBA length does not match its dimensions.", "frame");
            }
            if (drawWidth <= 0 || drawHeight <= 0) return 0;

            int startX = Math.Max(0, left);
            int startY = Math.Max(0, top);
            int endX = Math.Min(frameWidth, left + drawWidth);
            int endY = Math.Min(frameHeight, top + drawHeight);
            int changed = 0;
            for (int destinationY = startY; destinationY < endY; destinationY++)
            {
                int sourceY = Math.Min(glyph.Height - 1, (destinationY - top) * glyph.Height / drawHeight);
                for (int destinationX = startX; destinationX < endX; destinationX++)
                {
                    int sourceX = Math.Min(glyph.Width - 1, (destinationX - left) * glyph.Width / drawWidth);
                    int sourceOffset = 4 * (sourceY * glyph.Width + sourceX);
                    int alpha = glyph.RgbaTopDown[sourceOffset + 3];
                    if (alpha == 0) continue;

                    int destinationOffset = 4 * (destinationY * frameWidth + destinationX);
                    int inverseAlpha = 255 - alpha;
                    frame[destinationOffset] = Blend(glyph.RgbaTopDown[sourceOffset], frame[destinationOffset], alpha, inverseAlpha);
                    frame[destinationOffset + 1] = Blend(glyph.RgbaTopDown[sourceOffset + 1], frame[destinationOffset + 1], alpha, inverseAlpha);
                    frame[destinationOffset + 2] = Blend(glyph.RgbaTopDown[sourceOffset + 2], frame[destinationOffset + 2], alpha, inverseAlpha);
                    frame[destinationOffset + 3] = 255;
                    changed++;
                }
            }
            return changed;
        }

        private static byte Blend(byte source, byte destination, int alpha, int inverseAlpha)
        {
            return (byte)((source * alpha + destination * inverseAlpha + 127) / 255);
        }
    }
}
