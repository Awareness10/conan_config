#include <stdio.h>
#include <string.h>

#include <libxml/parser.h>
#include <libxml/tree.h>
#include <libxml/xmlsave.h>

int main(void) {
    static const char xml[] = "<a><b n=\"1\">text</b></a>";
    LIBXML_TEST_VERSION

    xmlDocPtr doc = xmlReadMemory(xml, (int)strlen(xml), "test.xml", NULL, 0);
    if (doc == NULL) {
        fprintf(stderr, "parse failed\n");
        return 1;
    }
    xmlNodePtr b = xmlDocGetRootElement(doc)->children;
    xmlChar *n = xmlGetProp(b, BAD_CAST "n");
    int ok = n != NULL && strcmp((const char *)n, "1") == 0;
    xmlFree(n);

    xmlChar *out = NULL;
    int size = 0;
    xmlDocDumpMemory(doc, &out, &size);
    printf("libxml2 %s: %s", xmlParserVersion, out);
    xmlFree(out);
    xmlFreeDoc(doc);
    return ok ? 0 : 1;
}
