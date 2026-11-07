"""Ultralytics AGPL-3.0 postprocess adapter: pass its existing class filter to NMS.

Based on ultralytics/models/yolo/detect/val.py in Ultralytics 8.3.228.
The upstream implementation filters GT with args.classes but omits that option
from its NMS call. This adds only that keyword; matching and metrics are inherited.
"""
from ultralytics.models.yolo.detect import DetectionValidator
from ultralytics.utils import nms


class ClassRestrictedValidator(DetectionValidator):
    def postprocess(self, preds):
        outputs = nms.non_max_suppression(
            preds,
            self.args.conf,
            self.args.iou,
            classes=self.args.classes,
            nc=0 if self.args.task == "detect" else self.nc,
            multi_label=True,
            agnostic=self.args.single_cls or self.args.agnostic_nms,
            max_det=self.args.max_det,
            end2end=self.end2end,
            rotated=self.args.task == "obb",
        )
        return [{"bboxes": x[:, :4], "conf": x[:, 4], "cls": x[:, 5], "extra": x[:, 6:]} for x in outputs]
