// vtsr: upscale a PNG sequence with macOS 26 VideoToolbox super resolution.
// build: clang -fobjc-arc -O2 -mmacosx-version-min=26.0 tools/vtsr.m -o out/vtsr \
//          -framework Foundation -framework VideoToolbox -framework CoreVideo -framework CoreMedia \
//          -framework ImageIO -framework CoreGraphics -framework UniformTypeIdentifiers
// usage: vtsr <inDir> <outDir> <scale> [preroll [outW outH]]
//   scale must be 4 (only factor Apple supports); input max 1920x1080. For 1920x540 -> 4K pass outW/outH 3840 1080.
//   inDir has f_0001.png ... ; outDir gets same names. preroll: number of last frames
//   fed first (not written) so frame 1 sees the same temporal history as a looped playback.
// Colour: the 8-bit input/output buffers are tagged BT.709 primaries + sRGB transfer (the PNGs are sRGB) and the
// BGRA <-> half-float transfers are lossless (measured: 0.00 levels round trip). The SR model itself shifts colour
// (measured on cable trays: blue about -1.3 levels, red/green -0.3), so after down-sampling each output frame gets a
// low-frequency colour fix: the difference source - box-down(output) is blurred (~17 px at source scale) and added
// back, which restores the source's colour/brightness while keeping the model's detail. VTSR_NO_COLORFIX=1 skips it.
// Output PNGs are sRGB-tagged like the input.
// Exit codes: 0 ok, 1 failure (unreadable/corrupt PNG, VT error, write error), 2 usage.
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#import <CoreVideo/CoreVideo.h>
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

static void die(const char *fmt, NSString *arg) {
  fprintf(stderr, "vtsr: ");
  fprintf(stderr, fmt, arg ? arg.UTF8String : "");
  fprintf(stderr, "\n");
  exit(1);
}

static void tagColour(CVPixelBufferRef pb) {
  CVBufferSetAttachment(pb, kCVImageBufferColorPrimariesKey, kCVImageBufferColorPrimaries_ITU_R_709_2, kCVAttachmentMode_ShouldNotPropagate);
  CVBufferSetAttachment(pb, kCVImageBufferTransferFunctionKey, kCVImageBufferTransferFunction_sRGB, kCVAttachmentMode_ShouldNotPropagate);
  CVBufferSetAttachment(pb, kCVImageBufferYCbCrMatrixKey, kCVImageBufferYCbCrMatrix_ITU_R_709_2, kCVAttachmentMode_ShouldNotPropagate);
}

static CVPixelBufferRef bgraFromPNG(NSString *path) { // NULL on missing/corrupt/0-byte file
  CGImageSourceRef src = CGImageSourceCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path], NULL);
  if (!src) return NULL;
  CGImageRef img = CGImageSourceGetCount(src) ? CGImageSourceCreateImageAtIndex(src, 0, NULL) : NULL;
  CFRelease(src);
  if (!img) return NULL;
  size_t w = CGImageGetWidth(img), h = CGImageGetHeight(img);
  NSDictionary *a = @{(id)kCVPixelBufferIOSurfacePropertiesKey: @{}, (id)kCVPixelBufferMetalCompatibilityKey: @YES};
  CVPixelBufferRef pb = NULL;
  if (CVPixelBufferCreate(NULL, w, h, kCVPixelFormatType_32BGRA, (__bridge CFDictionaryRef)a, &pb) || !pb) {
    CGImageRelease(img);
    return NULL;
  }
  CVPixelBufferLockBaseAddress(pb, 0);
  CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
  CGContextRef ctx = CGBitmapContextCreate(CVPixelBufferGetBaseAddress(pb), w, h, 8, CVPixelBufferGetBytesPerRow(pb), cs,
                                           kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little);
  if (ctx) {
    CGContextDrawImage(ctx, CGRectMake(0, 0, w, h), img);
    CGContextRelease(ctx);
  }
  CGColorSpaceRelease(cs); CGImageRelease(img);
  CVPixelBufferUnlockBaseAddress(pb, 0);
  if (!ctx) { CVPixelBufferRelease(pb); return NULL; }
  tagColour(pb);
  return pb;
}

static BOOL writePNG(CVPixelBufferRef pb, NSString *path) {
  CVPixelBufferLockBaseAddress(pb, kCVPixelBufferLock_ReadOnly);
  size_t w = CVPixelBufferGetWidth(pb), h = CVPixelBufferGetHeight(pb);
  CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
  CGContextRef ctx = CGBitmapContextCreate(CVPixelBufferGetBaseAddress(pb), w, h, 8, CVPixelBufferGetBytesPerRow(pb), cs,
                                           kCGImageAlphaNoneSkipFirst | kCGBitmapByteOrder32Little);
  CGImageRef img = ctx ? CGBitmapContextCreateImage(ctx) : NULL;
  CGImageDestinationRef d = img ? CGImageDestinationCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path],
                                                                  (__bridge CFStringRef)UTTypePNG.identifier, 1, NULL) : NULL;
  BOOL ok = NO;
  if (d) {
    CGImageDestinationAddImage(d, img, NULL); // image carries the sRGB colour space -> PNG gets an sRGB tag
    ok = CGImageDestinationFinalize(d);
    CFRelease(d);
  }
  if (img) CGImageRelease(img);
  if (ctx) CGContextRelease(ctx);
  CGColorSpaceRelease(cs);
  CVPixelBufferUnlockBaseAddress(pb, kCVPixelBufferLock_ReadOnly);
  return ok;
}

// separable box blur, radius r, edge clamp, in place on a w*h float plane
static void boxBlur(float *a, float *tmp, int w, int h, int r) {
  float inv = 1.0f / (2 * r + 1);
  for (int y = 0; y < h; y++) {
    float *row = a + (size_t)y * w, acc = 0;
    for (int k = -r; k <= r; k++) acc += row[k < 0 ? 0 : (k >= w ? w - 1 : k)];
    for (int x = 0; x < w; x++) {
      tmp[(size_t)y * w + x] = acc * inv;
      int xo = x - r < 0 ? 0 : x - r, xi = x + r + 1 >= w ? w - 1 : x + r + 1;
      acc += row[xi] - row[xo];
    }
  }
  for (int x = 0; x < w; x++) {
    float acc = 0;
    for (int k = -r; k <= r; k++) acc += tmp[(size_t)(k < 0 ? 0 : (k >= h ? h - 1 : k)) * w + x];
    for (int y = 0; y < h; y++) {
      a[(size_t)y * w + x] = acc * inv;
      int yo = y - r < 0 ? 0 : y - r, yi = y + r + 1 >= h ? h - 1 : y + r + 1;
      acc += tmp[(size_t)yi * w + x] - tmp[(size_t)yo * w + x];
    }
  }
}

// Low-frequency colour fix (see header). src and out are 32BGRA; out must be an integer multiple k of src in both axes.
static void colourFix(CVPixelBufferRef src, CVPixelBufferRef out) {
  int w = (int)CVPixelBufferGetWidth(src), h = (int)CVPixelBufferGetHeight(src);
  int W = (int)CVPixelBufferGetWidth(out), H = (int)CVPixelBufferGetHeight(out);
  if (W % w || H % h || W / w != H / h) { fprintf(stderr, "vtsr: output not an integer multiple of input, colour fix skipped\n"); return; }
  int k = W / w;
  CVPixelBufferLockBaseAddress(src, kCVPixelBufferLock_ReadOnly);
  CVPixelBufferLockBaseAddress(out, 0);
  const uint8_t *sp = CVPixelBufferGetBaseAddress(src);
  uint8_t *op = CVPixelBufferGetBaseAddress(out);
  size_t sbr = CVPixelBufferGetBytesPerRow(src), obr = CVPixelBufferGetBytesPerRow(out);
  float *d = malloc(sizeof(float) * w * h), *tmp = malloc(sizeof(float) * w * h);
  float invk2 = 1.0f / (k * k);
  for (int c = 0; c < 3; c++) { // B, G, R
    for (int y = 0; y < h; y++)
      for (int x = 0; x < w; x++) {
        int sum = 0;
        for (int j = 0; j < k; j++) {
          const uint8_t *o = op + (size_t)(y * k + j) * obr + (size_t)x * k * 4 + c;
          for (int i = 0; i < k; i++) sum += o[i * 4];
        }
        d[(size_t)y * w + x] = sp[(size_t)y * sbr + (size_t)x * 4 + c] - sum * invk2;
      }
    boxBlur(d, tmp, w, h, 6); boxBlur(d, tmp, w, h, 6); // ~gaussian, sigma ~5 px at source scale
    for (int Y = 0; Y < H; Y++) {
      float fy = (Y + 0.5f) / k - 0.5f; if (fy < 0) fy = 0; if (fy > h - 1) fy = h - 1;
      int y0 = (int)fy, y1 = y0 + 1 < h ? y0 + 1 : y0; float ty = fy - y0;
      uint8_t *orow = op + (size_t)Y * obr;
      for (int X = 0; X < W; X++) {
        float fx = (X + 0.5f) / k - 0.5f; if (fx < 0) fx = 0; if (fx > w - 1) fx = w - 1;
        int x0 = (int)fx, x1 = x0 + 1 < w ? x0 + 1 : x0; float tx = fx - x0;
        float v = (d[(size_t)y0 * w + x0] * (1 - tx) + d[(size_t)y0 * w + x1] * tx) * (1 - ty) +
                  (d[(size_t)y1 * w + x0] * (1 - tx) + d[(size_t)y1 * w + x1] * tx) * ty;
        float o = orow[X * 4 + c] + v + 0.5f;
        orow[X * 4 + c] = o < 0 ? 0 : (o > 255 ? 255 : (uint8_t)o);
      }
    }
  }
  free(d); free(tmp);
  CVPixelBufferUnlockBaseAddress(out, 0);
  CVPixelBufferUnlockBaseAddress(src, kCVPixelBufferLock_ReadOnly);
}

static CVPixelBufferRef makeBuffer(NSDictionary *attrs, size_t w, size_t h) {
  NSMutableDictionary *a = [attrs mutableCopy];
  a[(id)kCVPixelBufferWidthKey] = @(w);
  a[(id)kCVPixelBufferHeightKey] = @(h);
  OSType fmt = kCVPixelFormatType_32BGRA;
  id f = attrs[(id)kCVPixelBufferPixelFormatTypeKey];
  if ([f isKindOfClass:[NSArray class]]) f = [f firstObject];
  if (f) fmt = [f unsignedIntValue];
  [a removeObjectForKey:(id)kCVPixelBufferPixelFormatTypeKey];
  CVPixelBufferRef pb = NULL;
  CVReturn r = CVPixelBufferCreate(NULL, w, h, fmt, (__bridge CFDictionaryRef)a, &pb);
  if (r || !pb) { fprintf(stderr, "vtsr: CVPixelBufferCreate %d fmt %.4s\n", r, (char *)&fmt); exit(1); }
  if (fmt == kCVPixelFormatType_32BGRA) tagColour(pb); // model buffers stay untagged: tags change the model's output
  return pb;
}

static void transfer(VTPixelTransferSessionRef xfer, CVPixelBufferRef from, CVPixelBufferRef to) {
  OSStatus s = VTPixelTransferSessionTransferImage(xfer, from, to);
  if (s != noErr) { fprintf(stderr, "vtsr: VTPixelTransferSessionTransferImage failed (%d)\n", (int)s); exit(1); }
}

int main(int argc, const char **argv) {
  @autoreleasepool {
    if (argc < 4) { fprintf(stderr, "usage: vtsr inDir outDir scale [preroll [outW outH]]\n"); return 2; }
    NSString *inDir = @(argv[1]), *outDir = @(argv[2]);
    NSInteger scale = atoi(argv[3]);
    int preroll = argc > 4 ? atoi(argv[4]) : 8;
    int outW = argc > 6 ? atoi(argv[5]) : 0, outH = argc > 6 ? atoi(argv[6]) : 0;
    if (scale < 1 || preroll < 0 || outW < 0 || outH < 0) { fprintf(stderr, "vtsr: bad numeric argument\n"); return 2; }
    if (!VTSuperResolutionScalerConfiguration.isSupported) { fprintf(stderr, "vtsr: super resolution not supported\n"); return 1; }
    NSError *lerr = nil;
    NSArray *all = [NSFileManager.defaultManager contentsOfDirectoryAtPath:inDir error:&lerr];
    if (!all) die("cannot list %s", inDir);
    NSArray *files = [[all filteredArrayUsingPredicate:[NSPredicate predicateWithFormat:@"SELF ENDSWITH '.png'"]]
        sortedArrayUsingSelector:@selector(compare:)];
    if (!files.count) die("no png in %s", inDir);
    if (![NSFileManager.defaultManager createDirectoryAtPath:outDir withIntermediateDirectories:YES attributes:nil error:nil])
      die("cannot create %s", outDir);

    NSString *p0 = [inDir stringByAppendingPathComponent:files[0]];
    CVPixelBufferRef first = bgraFromPNG(p0);
    if (!first) die("cannot decode %s (corrupt or 0-byte PNG?)", p0);
    size_t w = CVPixelBufferGetWidth(first), h = CVPixelBufferGetHeight(first);
    CVPixelBufferRelease(first);

    VTSuperResolutionScalerConfiguration *cfg = [[VTSuperResolutionScalerConfiguration alloc]
        initWithFrameWidth:w frameHeight:h scaleFactor:scale
                 inputType:VTSuperResolutionScalerConfigurationInputTypeVideo
        usePrecomputedFlow:NO
     qualityPrioritization:VTSuperResolutionScalerConfigurationQualityPrioritizationNormal
                  revision:VTSuperResolutionScalerConfiguration.defaultRevision];
    if (!cfg) { fprintf(stderr, "vtsr: config failed for %zux%zu x%ld (supported scales: %s)\n", w, h, (long)scale,
                        [[VTSuperResolutionScalerConfiguration.supportedScaleFactors description] UTF8String]); return 1; }

    if (cfg.configurationModelStatus != VTSuperResolutionScalerConfigurationModelStatusReady) {
      fprintf(stderr, "model status %ld, downloading Apple model...\n", (long)cfg.configurationModelStatus);
      dispatch_semaphore_t s = dispatch_semaphore_create(0);
      __block NSError *de = nil;
      [cfg downloadConfigurationModelWithCompletionHandler:^(NSError *e) { de = e; dispatch_semaphore_signal(s); }];
      dispatch_semaphore_wait(s, DISPATCH_TIME_FOREVER);
      if (de) { fprintf(stderr, "vtsr: download error %s\n", de.description.UTF8String); return 1; }
    }

    VTFrameProcessor *proc = [VTFrameProcessor new];
    NSError *err = nil;
    if (![proc startSessionWithConfiguration:cfg error:&err]) { fprintf(stderr, "vtsr: session %s\n", err.description.UTF8String); return 1; }

    VTPixelTransferSessionRef xfer = NULL;
    if (VTPixelTransferSessionCreate(NULL, &xfer) != noErr || !xfer) { fprintf(stderr, "vtsr: VTPixelTransferSessionCreate failed\n"); return 1; }
    NSDictionary *srcA = cfg.sourcePixelBufferAttributes, *dstA = cfg.destinationPixelBufferAttributes;

    // order: last `preroll` frames (warm-up, not written), then all frames
    NSMutableArray *order = [NSMutableArray array];
    int n = (int)files.count;
    if (preroll > n) preroll = n;
    for (int i = n - preroll; i < n; i++) [order addObject:@[@(i), @NO]];
    for (int i = 0; i < n; i++) [order addObject:@[@(i), @YES]];

    BOOL colourFixOff = getenv("VTSR_NO_COLORFIX") && *getenv("VTSR_NO_COLORFIX") && strcmp(getenv("VTSR_NO_COLORFIX"), "0");
    VTFrameProcessorFrame *prevIn = nil, *prevOut = nil;
    int64_t t = 0;
    NSDate *t0 = [NSDate date];
    for (NSArray *step in order) {
      @autoreleasepool {
        int i = [step[0] intValue];
        BOOL write = [step[1] boolValue];
        NSString *ip = [inDir stringByAppendingPathComponent:files[i]];
        CVPixelBufferRef bgra = bgraFromPNG(ip);
        if (!bgra) die("cannot decode %s (corrupt or 0-byte PNG?)", ip);
        if (CVPixelBufferGetWidth(bgra) != w || CVPixelBufferGetHeight(bgra) != h) die("size differs from first frame: %s", ip);
        CVPixelBufferRef src = makeBuffer(srcA, w, h);
        transfer(xfer, bgra, src);
        CVPixelBufferRef dst = makeBuffer(dstA, w * scale, h * scale);
        CMTime pts = CMTimeMake(t++, 30);
        VTFrameProcessorFrame *inF = [[VTFrameProcessorFrame alloc] initWithBuffer:src presentationTimeStamp:pts];
        VTFrameProcessorFrame *outF = [[VTFrameProcessorFrame alloc] initWithBuffer:dst presentationTimeStamp:pts];
        VTSuperResolutionScalerParameters *p = [[VTSuperResolutionScalerParameters alloc]
            initWithSourceFrame:inF previousFrame:prevIn previousOutputFrame:prevOut opticalFlow:nil
                 submissionMode:(prevIn ? VTSuperResolutionScalerParametersSubmissionModeSequential
                                        : VTSuperResolutionScalerParametersSubmissionModeRandom)
               destinationFrame:outF];
        if (![proc processWithParameters:p error:&err]) { fprintf(stderr, "vtsr: process %s\n", err.description.UTF8String); return 1; }
        if (write) {
          CVPixelBufferRef outBGRA = makeBuffer(@{(id)kCVPixelBufferIOSurfacePropertiesKey: @{},
                                                  (id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA)},
                                                outW ? outW : w * scale, outH ? outH : h * scale);
          transfer(xfer, dst, outBGRA);
          if (!colourFixOff) colourFix(bgra, outBGRA);
          NSString *op = [outDir stringByAppendingPathComponent:files[i]];
          if (!writePNG(outBGRA, op)) die("cannot write %s", op);
          CVPixelBufferRelease(outBGRA);
        }
        prevIn = inF; prevOut = outF;
        CVPixelBufferRelease(bgra); CVPixelBufferRelease(src); CVPixelBufferRelease(dst);
      }
    }
    [proc endSession];
    VTPixelTransferSessionInvalidate(xfer); CFRelease(xfer);
    printf("%d frames %zux%zu -> %zux%zu in %.1f s\n", n, w, h, w * scale, h * scale, -[t0 timeIntervalSinceNow]);
  }
  return 0;
}
