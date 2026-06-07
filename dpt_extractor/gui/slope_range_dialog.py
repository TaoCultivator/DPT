from __future__ import annotations



from PyQt6.QtWidgets import (

    QDialog,

    QDialogButtonBox,

    QDoubleSpinBox,

    QFormLayout,

    QLabel,

    QVBoxLayout,

)



from dpt_extractor.gui.theme import DARK_STYLESHEET

from dpt_extractor.models.slope_range import SlopeRange





class SlopeRangeDialog(QDialog):

    """自定义 di/dt、dv/dt 百分比起止点。"""



    def __init__(

        self,

        parent=None,

        title: str = "自定义取值范围",

        initial: SlopeRange | None = None,

        *,

        ic_reference: str = "plateau",

    ):

        super().__init__(parent)

        self.setWindowTitle(title)

        self.setMinimumWidth(320)

        self.setStyleSheet(DARK_STYLESHEET)

        self._result: SlopeRange | None = None

        self._ic_reference = ic_reference



        layout = QVBoxLayout(self)

        if ic_reference == "if_irm":

            hint_text = (

                "零基准算法：thA = H0 + 起点%·(Ha−H0)，thB = H0 + 终点%·(Hb−H0)。"

                "50%IF→50%IRM 时起点/终点均为 50%。"

            )

        elif ic_reference == "idm":

            hint_text = "IDM 算法：Ha=0、Hb=IDM，沿换流前下降沿在两者之间按百分比穿越。"

        else:

            hint_text = "输入电流或电压幅值的起止百分比（沿开关方向穿越）。"

        hint = QLabel(hint_text)

        hint.setWordWrap(True)

        hint.setStyleSheet("color:#a6adc8;font-size:12px;")

        layout.addWidget(hint)



        form = QFormLayout()

        self.spin_start = QDoubleSpinBox()

        self.spin_end = QDoubleSpinBox()

        for sp in (self.spin_start, self.spin_end):

            sp.setRange(0.0, 100.0)

            sp.setDecimals(1)

            sp.setSuffix(" %")

            sp.setSingleStep(5.0)

        init = initial or SlopeRange(90.0, 10.0)

        self.spin_start.setValue(init.start_pct)

        self.spin_end.setValue(init.end_pct)

        form.addRow("起点", self.spin_start)

        form.addRow("终点", self.spin_end)

        layout.addLayout(form)



        buttons = QDialogButtonBox(

            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel

        )

        buttons.accepted.connect(self._accept)

        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)



    def range_value(self) -> SlopeRange | None:

        return self._result



    def _accept(self) -> None:

        a, b = self.spin_start.value(), self.spin_end.value()

        if abs(a - b) < 0.1:

            return

        direction = "fall" if a > b else "rise"

        preset_label = ""

        if self._ic_reference == "if_irm":

            preset_label = f"{a:g}%IF→{b:g}%IRM"

        self._result = SlopeRange(

            a,

            b,

            ic_reference=self._ic_reference,

            ic_direction=direction,

            preset_label=preset_label,

        )

        self.accept()

