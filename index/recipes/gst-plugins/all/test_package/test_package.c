#include <stdio.h>
#include <string.h>

#include <gst/app/gstappsink.h>
#include <gst/gst.h>

/* Runs a pipeline through elements from base and good, pulls the result
 * through appsink, checks elements from bad, and reports what the nvcodec plugin registered. */
int main(int argc, char **argv) {
    gst_init(NULL, NULL);
    printf("%s\n", gst_version_string());

    GError *err = NULL;
    GstElement *pipeline = gst_parse_launch(
        "videotestsrc num-buffers=10 ! videoconvertscale ! video/x-raw,width=64,height=48 "
        "! videoflip method=clockwise ! y4menc ! appsink name=sink",
        &err);
    if (!pipeline) {
        fprintf(stderr, "pipeline: %s\n", err->message);
        return 1;
    }
    GstAppSink *sink = GST_APP_SINK(gst_bin_get_by_name(GST_BIN(pipeline), "sink"));
    gst_element_set_state(pipeline, GST_STATE_PLAYING);
    int buffers = 0;
    GstSample *sample;
    while ((sample = gst_app_sink_pull_sample(sink))) {
        buffers++;
        gst_sample_unref(sample);
    }
    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(sink);
    gst_object_unref(pipeline);
    printf("pulled %d buffers\n", buffers);

    /* h264parse (bad) and rtph264pay (good): what an nvh264enc pipeline needs. */
    const char *needed[] = {"h264parse", "h265parse", "rtph264pay", "mpegtsmux", "glimagesink"};
    int ok = buffers == 10;
    for (size_t i = 0; i < sizeof(needed) / sizeof(*needed); i++) {
        GstElementFactory *f = gst_element_factory_find(needed[i]);
        printf("%-12s %s\n", needed[i], f ? "yes" : "no");
        if (f)
            gst_object_unref(f);
        else if (strcmp(needed[i], "glimagesink") != 0)
            ok = 0;
    }

    if (argc > 1 && strcmp(argv[1], "True") == 0) {
        /* The plugin must load; its encoders only register with an NVIDIA driver. */
        GstPlugin *nv = gst_registry_find_plugin(gst_registry_get(), "nvcodec");
        if (!nv) {
            fprintf(stderr, "nvcodec plugin not found\n");
            return 1;
        }
        GList *features = gst_registry_get_feature_list_by_plugin(gst_registry_get(), "nvcodec");
        printf("nvcodec:");
        for (GList *l = features; l; l = l->next)
            printf(" %s", gst_plugin_feature_get_name(l->data));
        printf("\n");
        gst_plugin_feature_list_free(features);
        gst_object_unref(nv);
    }
    return ok ? 0 : 1;
}
