/*
 * Input to bindgen for the constants that src/pg_constants_<version>.rs
 * copies by hand; a test compares the two (Loams-Patch LP-0040).
 */
#include "postgres.h"
#include "access/xact.h"
#include "access/xlogrecord.h"
#include "access/heapam_xlog.h"
#include "catalog/catversion.h"
#include "catalog/pg_control.h"
#include "commands/dbcommands_xlog.h"
#include "storage/sinval.h"
