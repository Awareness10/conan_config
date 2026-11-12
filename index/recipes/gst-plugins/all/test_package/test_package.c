#include <stdio.h>
#include <string.h>

#include <gst/app/gstappsink.h>
#include <gst/gst.h>
#include <gst/rtsp-server/rtsp-server.h>

static gpointer run_loop(gpointer loop) {
    g_main_loop_run(loop);
    return NULL;
}

/* gst-rtsp-server serves raw video on a free localhost port; rtspsrc (good) receives
 * it over TCP. True when 5 frames arrive. */
static int rtsp_loopback(void) {
    GMainContext *ctx = g_main_context_new();
    GMainLoop *loop = g_main_loop_new(ctx, FALSE);
    GstRTSPServer *server = gst_rtsp_server_new();
    gst_rtsp_server_set_address(server, "127.0.0.1");
    gst_rtsp_server_set_service(server, "0");
    GstRTSPMediaFactory *factory = gst_rtsp_media_factory_new();
    gst_rtsp_media_factory_set_launch(
        factory, "( videotestsrc ! video/x-raw,format=RGB,width=64,height=48,framerate=30/1 "
                 "! rtpvrawpay name=pay0 pt=96 )");
    GstRTSPMountPoints *mounts = gst_rtsp_server_get_mount_points(server);
    gst_rtsp_mount_points_add_factory(mounts, "/test", factory);
    g_object_unref(mounts);
    guint source = gst_rtsp_server_attach(server, ctx);
    GThread *thread = g_thread_new("rtsp-server", run_loop, loop);

    gchar *desc = g_strdup_printf("rtspsrc location=rtsp://127.0.0.1:%d/test protocols=tcp "
                                  "! rtpvrawdepay ! appsink name=sink",
                                  gst_rtsp_server_get_bound_port(server));
    GstElement *client = gst_parse_launch(desc, NULL);
    g_free(desc);
    int frames = 0;
    if (client) {
        GstAppSink *sink = GST_APP_SINK(gst_bin_get_by_name(GST_BIN(client), "sink"));
        gst_element_set_state(client, GST_STATE_PLAYING);
        GstSample *sample;
        while (frames < 5 && (sample = gst_app_sink_try_pull_sample(sink, 5 * GST_SECOND))) {
            frames++;
            gst_sample_unref(sample);
        }
        gst_element_set_state(client, GST_STATE_NULL);
        gst_object_unref(sink);
        gst_object_unref(client);
    }

    g_main_loop_quit(loop);
    g_thread_join(thread);
    g_source_destroy(g_main_context_find_source_by_id(ctx, source));
    g_object_unref(server);
    g_main_loop_unref(loop);
    g_main_context_unref(ctx);
    printf("rtsp loopback: %d frames\n", frames);
    return frames == 5;
}

/* Runs a pipeline through elements from base and good, pulls the result
 * through appsink, checks elements from bad, streams over RTSP with gst-rtsp-server,
 * and reports what the nvcodec plugin registered. */
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
    const char *needed[] = {"h264parse", "h265parse", "rtph264pay", "mpegtsmux", "rtspclientsink",
                            "glimagesink"};
    int ok = buffers == 10;
    for (size_t i = 0; i < sizeof(needed) / sizeof(*needed); i++) {
        GstElementFactory *f = gst_element_factory_find(needed[i]);
        printf("%-12s %s\n", needed[i], f ? "yes" : "no");
        if (f)
            gst_object_unref(f);
        else if (strcmp(needed[i], "glimagesink") != 0)
            ok = 0;
    }

    if (!rtsp_loopback())
        ok = 0;

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
