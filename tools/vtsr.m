// vtsr: upscale a PNG sequence with macOS 26 VideoToolbox super resolution.
// build: clang -fobjc-arc -O2 -mmacosx-version-min=26.0 tools/vtsr.m -o out/vtsr \
//          -framework Foundation -framework VideoToolbox -framework CoreVideo -framework CoreMedia \
//          -framework ImageIO -framework CoreGraphics -framework UniformTypeIdentifiers
// usage: vtsr <inDir> <outDir> <scale> [preroll [outW outH]]
//   scale must be 4 (only factor Apple supports); input max 1920x1080. For 1920x540 -> 4K pass outW/outH 3840 1080.
//   inDir has f_0001.png ... ; outDir gets same names. preroll: number of last frames
//   fed first (not written) so frame 1 sees the same temporal history as a looped playback.
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#import <CoreVideo/CoreVideo.h>
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

static CVPixelBufferRef bgraFromPNG(NSString *path) {
  CGImageSourceRef src = CGImageSourceCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path], NULL);
  if (!src) return NULL;
  CGImageRef img = CGImageSourceCreateImageAtIndex(src, 0, NULL);
  CFRelease(src);
  size_t w = CGImageGetWidth(img), h = CGImageGetHeight(img);
  NSDictionary *a = @{(id)kCVPixelBufferIOSurfacePropertiesKey: @{}, (id)kCVPixelBufferMetalCompatibilityKey: @YES};
  CVPixelBufferRef pb = NULL;
  CVPixelBufferCreate(NULL, w, h, kCVPixelFormatType_32BGRA, (__bridge CFDictionaryRef)a, &pb);
  CVPixelBufferLockBaseAddress(pb, 0);
  CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
  CGContextRef ctx = CGBitmapContextCreate(CVPixelBufferGetBaseAddress(pb), w, h, 8, CVPixelBufferGetBytesPerRow(pb), cs,
                                           kCGImageAlphaPremultipliedFirst | kCGBitmapByteOrder32Little);
  CGContextDrawImage(ctx, CGRectMake(0, 0, w, h), img);
  CGContextRelease(ctx); CGColorSpaceRelease(cs); CGImageRelease(img);
  CVPixelBufferUnlockBaseAddress(pb, 0);
  return pb;
}

static void writePNG(CVPixelBufferRef pb, NSString *path) {
  CVPixelBufferLockBaseAddress(pb, kCVPixelBufferLock_ReadOnly);
  size_t w = CVPixelBufferGetWidth(pb), h = CVPixelBufferGetHeight(pb);
  CGColorSpaceRef cs = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
  CGContextRef ctx = CGBitmapContextCreate(CVPixelBufferGetBaseAddress(pb), w, h, 8, CVPixelBufferGetBytesPerRow(pb), cs,
                                           kCGImageAlphaNoneSkipFirst | kCGBitmapByteOrder32Little);
  CGImageRef img = CGBitmapContextCreateImage(ctx);
  CGImageDestinationRef d = CGImageDestinationCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path],
                                                            (__bridge CFStringRef)UTTypePNG.identifier, 1, NULL);
  CGImageDestinationAddImage(d, img, NULL);
  CGImageDestinationFinalize(d);
  CFRelease(d); CGImageRelease(img); CGContextRelease(ctx); CGColorSpaceRelease(cs);
  CVPixelBufferUnlockBaseAddress(pb, kCVPixelBufferLock_ReadOnly);
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
  if (r) { fprintf(stderr, "CVPixelBufferCreate %d fmt %.4s\n", r, (char *)&fmt); exit(1); }
  return pb;
}

int main(int argc, const char **argv) {
  @autoreleasepool {
    if (argc < 4) { fprintf(stderr, "usage: vtsr inDir outDir scale [preroll [outW outH]]\n"); return 2; }
    NSString *inDir = @(argv[1]), *outDir = @(argv[2]);
    NSInteger scale = atoi(argv[3]);
    int preroll = argc > 4 ? atoi(argv[4]) : 8;
    int outW = argc > 6 ? atoi(argv[5]) : 0, outH = argc > 6 ? atoi(argv[6]) : 0;
    if (!VTSuperResolutionScalerConfiguration.isSupported) { fprintf(stderr, "super resolution not supported\n"); return 1; }
    NSArray *files = [[[NSFileManager.defaultManager contentsOfDirectoryAtPath:inDir error:nil]
        filteredArrayUsingPredicate:[NSPredicate predicateWithFormat:@"SELF ENDSWITH '.png'"]]
        sortedArrayUsingSelector:@selector(compare:)];
    if (!files.count) { fprintf(stderr, "no png\n"); return 1; }
    [NSFileManager.defaultManager createDirectoryAtPath:outDir withIntermediateDirectories:YES attributes:nil error:nil];

    CVPixelBufferRef first = bgraFromPNG([inDir stringByAppendingPathComponent:files[0]]);
    size_t w = CVPixelBufferGetWidth(first), h = CVPixelBufferGetHeight(first);
    CVPixelBufferRelease(first);

    VTSuperResolutionScalerConfiguration *cfg = [[VTSuperResolutionScalerConfiguration alloc]
        initWithFrameWidth:w frameHeight:h scaleFactor:scale
                 inputType:VTSuperResolutionScalerConfigurationInputTypeVideo
        usePrecomputedFlow:NO
     qualityPrioritization:VTSuperResolutionScalerConfigurationQualityPrioritizationNormal
                  revision:VTSuperResolutionScalerConfiguration.defaultRevision];
    if (!cfg) { fprintf(stderr, "config failed for %zux%zu x%ld (supported scales: %s)\n", w, h, (long)scale,
                        [[VTSuperResolutionScalerConfiguration.supportedScaleFactors description] UTF8String]); return 1; }

    if (cfg.configurationModelStatus != VTSuperResolutionScalerConfigurationModelStatusReady) {
      fprintf(stderr, "model status %ld, downloading Apple model...\n", (long)cfg.configurationModelStatus);
      dispatch_semaphore_t s = dispatch_semaphore_create(0);
      __block NSError *de = nil;
      [cfg downloadConfigurationModelWithCompletionHandler:^(NSError *e) { de = e; dispatch_semaphore_signal(s); }];
      dispatch_semaphore_wait(s, DISPATCH_TIME_FOREVER);
      if (de) { fprintf(stderr, "download error %s\n", de.description.UTF8String); return 1; }
    }

    VTFrameProcessor *proc = [VTFrameProcessor new];
    NSError *err = nil;
    if (![proc startSessionWithConfiguration:cfg error:&err]) { fprintf(stderr, "session %s\n", err.description.UTF8String); return 1; }

    VTPixelTransferSessionRef xfer = NULL;
    VTPixelTransferSessionCreate(NULL, &xfer);
    NSDictionary *srcA = cfg.sourcePixelBufferAttributes, *dstA = cfg.destinationPixelBufferAttributes;

    // order: last `preroll` frames (warm-up, not written), then all frames
    NSMutableArray *order = [NSMutableArray array];
    int n = (int)files.count;
    if (preroll > n) preroll = n;
    for (int i = n - preroll; i < n; i++) [order addObject:@[@(i), @NO]];
    for (int i = 0; i < n; i++) [order addObject:@[@(i), @YES]];

    VTFrameProcessorFrame *prevIn = nil, *prevOut = nil;
    int64_t t = 0;
    NSDate *t0 = [NSDate date];
    for (NSArray *step in order) {
      @autoreleasepool {
        int i = [step[0] intValue];
        BOOL write = [step[1] boolValue];
        CVPixelBufferRef bgra = bgraFromPNG([inDir stringByAppendingPathComponent:files[i]]);
        CVPixelBufferRef src = makeBuffer(srcA, w, h);
        VTPixelTransferSessionTransferImage(xfer, bgra, src);
        CVPixelBufferRef dst = makeBuffer(dstA, w * scale, h * scale);
        CMTime pts = CMTimeMake(t++, 30);
        VTFrameProcessorFrame *inF = [[VTFrameProcessorFrame alloc] initWithBuffer:src presentationTimeStamp:pts];
        VTFrameProcessorFrame *outF = [[VTFrameProcessorFrame alloc] initWithBuffer:dst presentationTimeStamp:pts];
        VTSuperResolutionScalerParameters *p = [[VTSuperResolutionScalerParameters alloc]
            initWithSourceFrame:inF previousFrame:prevIn previousOutputFrame:prevOut opticalFlow:nil
                 submissionMode:(prevIn ? VTSuperResolutionScalerParametersSubmissionModeSequential
                                        : VTSuperResolutionScalerParametersSubmissionModeRandom)
               destinationFrame:outF];
        if (![proc processWithParameters:p error:&err]) { fprintf(stderr, "process %s\n", err.description.UTF8String); return 1; }
        if (write) {
          CVPixelBufferRef outBGRA = makeBuffer(@{(id)kCVPixelBufferIOSurfacePropertiesKey: @{},
                                                  (id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA)},
                                                outW ? outW : w * scale, outH ? outH : h * scale);
          VTPixelTransferSessionTransferImage(xfer, dst, outBGRA);
          writePNG(outBGRA, [outDir stringByAppendingPathComponent:files[i]]);
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
